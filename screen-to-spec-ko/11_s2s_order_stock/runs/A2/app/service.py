"""주문/재고 비즈니스 로직.

재고 규칙
- 주문 접수(PENDING): 재고 변화 없음
- 확정(CONFIRMED): 재고 차감 (부족하면 전체 실패, 아무것도 차감되지 않음)
- 출고(SHIPPED): 재고 변화 없음 (확정 때 이미 차감)
- 취소(CANCELLED): PENDING/CONFIRMED 에서만 가능. CONFIRMED 였다면 재고 복원
- 환불(REFUNDED): 관리자 전용, SHIPPED 에서만 가능. 반품 입고 시 재고 복원(restock=True)

모든 상태 전이는 `UPDATE ... WHERE status = <기대 상태>` 로 선점하므로
더블 클릭/동시 요청이 와도 재고가 두 번 차감·복원되지 않는다.
"""
import sqlite3

from .db import tx


class BizError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.message = message
        self.status = status


def _order_items(conn, order_id):
    return conn.execute(
        "SELECT oi.product_id, oi.qty, p.name FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id WHERE oi.order_id = ? ORDER BY oi.id",
        (order_id,),
    ).fetchall()


def _claim(conn, order_id, allowed, new_status, actor, note=""):
    """주문 상태를 allowed 중 하나에서 new_status 로 원자적으로 전이. 이전 상태를 반환."""
    row = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        raise BizError("주문을 찾을 수 없습니다.", 404)
    old = row["status"]
    if old not in allowed:
        raise BizError(f"현재 상태({old})에서는 '{new_status}' 처리를 할 수 없습니다.")
    cur = conn.execute(
        "UPDATE orders SET status = ?, updated_at = datetime('now','localtime') "
        "WHERE id = ? AND status = ?",
        (new_status, order_id, old),
    )
    if cur.rowcount != 1:
        raise BizError("다른 처리가 먼저 반영되었습니다. 새로고침 후 다시 시도하세요.")
    conn.execute(
        "INSERT INTO order_events (order_id, from_status, to_status, actor, note) VALUES (?,?,?,?,?)",
        (order_id, old, new_status, actor, note),
    )
    return old


def _deduct(conn, order_id, actor, reason):
    shortages = []
    for it in _order_items(conn, order_id):
        cur = conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (it["qty"], it["product_id"], it["qty"]),
        )
        if cur.rowcount != 1:
            have = conn.execute("SELECT stock FROM products WHERE id = ?", (it["product_id"],)).fetchone()
            shortages.append(f"{it['name']} (필요 {it['qty']}, 재고 {have['stock']})")
            continue
        conn.execute(
            "INSERT INTO stock_movements (product_id, delta, reason, order_id, actor) VALUES (?,?,?,?,?)",
            (it["product_id"], -it["qty"], reason, order_id, actor),
        )
    if shortages:
        # 예외 → tx() 가 롤백하므로 앞서 차감된 품목도 모두 되돌려진다.
        raise BizError("재고 부족: " + ", ".join(shortages))


def _restock(conn, order_id, actor, reason):
    for it in _order_items(conn, order_id):
        conn.execute("UPDATE products SET stock = stock + ? WHERE id = ?", (it["qty"], it["product_id"]))
        conn.execute(
            "INSERT INTO stock_movements (product_id, delta, reason, order_id, actor) VALUES (?,?,?,?,?)",
            (it["product_id"], it["qty"], reason, order_id, actor),
        )


def create_order(customer, phone, address, items, actor):
    merged = {}
    for pid, qty in items:
        merged[pid] = merged.get(pid, 0) + qty
    with tx() as conn:
        total = 0
        lines = []
        for pid, qty in merged.items():
            p = conn.execute("SELECT id, price FROM products WHERE id = ?", (pid,)).fetchone()
            if p is None:
                raise BizError(f"존재하지 않는 상품입니다 (id={pid}).", 404)
            lines.append((pid, qty, p["price"]))
            total += qty * p["price"]
        cur = conn.execute(
            "INSERT INTO orders (customer, phone, address, status, total) VALUES (?,?,?,'PENDING',?)",
            (customer, phone, address, total),
        )
        oid = cur.lastrowid
        for pid, qty, price in lines:
            conn.execute(
                "INSERT INTO order_items (order_id, product_id, qty, unit_price) VALUES (?,?,?,?)",
                (oid, pid, qty, price),
            )
        conn.execute(
            "INSERT INTO order_events (order_id, from_status, to_status, actor, note) VALUES (?,NULL,'PENDING',?,'주문 접수')",
            (oid, actor),
        )
        return oid


def confirm_order(order_id, actor):
    with tx() as conn:
        _claim(conn, order_id, ("PENDING",), "CONFIRMED", actor)
        _deduct(conn, order_id, actor, "주문 확정 출고예정 차감")


def ship_order(order_id, actor):
    with tx() as conn:
        _claim(conn, order_id, ("CONFIRMED",), "SHIPPED", actor)


def cancel_order(order_id, actor, note=""):
    with tx() as conn:
        old = _claim(conn, order_id, ("PENDING", "CONFIRMED"), "CANCELLED", actor, note)
        if old == "CONFIRMED":
            _restock(conn, order_id, actor, "주문 취소 재고 복원")


def refund_order(order_id, actor, restock=True, note=""):
    with tx() as conn:
        _claim(conn, order_id, ("SHIPPED",), "REFUNDED", actor, note + (" [반품 재입고]" if restock else " [재입고 안 함]"))
        if restock:
            _restock(conn, order_id, actor, "환불 반품 재고 복원")


def adjust_stock(product_id, delta, reason, actor):
    with tx() as conn:
        cur = conn.execute(
            "UPDATE products SET stock = stock + ? WHERE id = ? AND stock + ? >= 0",
            (delta, product_id, delta),
        )
        if cur.rowcount != 1:
            exists = conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone()
            if not exists:
                raise BizError("존재하지 않는 상품입니다.", 404)
            raise BizError("재고는 0 미만이 될 수 없습니다.")
        conn.execute(
            "INSERT INTO stock_movements (product_id, delta, reason, order_id, actor) VALUES (?,?,?,NULL,?)",
            (product_id, delta, reason or "수동 조정", actor),
        )
