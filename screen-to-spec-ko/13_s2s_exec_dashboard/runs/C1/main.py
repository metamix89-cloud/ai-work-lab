import csv
import os
import re
import sqlite3
from datetime import date, datetime, timedelta

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "biz.db")

app = FastAPI()


def load_db():
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
        CREATE TABLE biz_users (user_id TEXT PRIMARY KEY, name TEXT, role TEXT);
        CREATE TABLE biz_orders (order_id TEXT, ordered_at TEXT, customer TEXT, amount INTEGER, status TEXT);
        CREATE TABLE biz_stock (sku TEXT, name TEXT, qty INTEGER, safety_qty INTEGER);
        CREATE TABLE biz_inquiries (inquiry_id TEXT, received_at TEXT, channel TEXT, status TEXT);
    """)
    spec = [("users", "biz_users", ["user_id", "name", "role"], []),
            ("orders", "biz_orders", ["order_id", "ordered_at", "customer", "amount", "status"], ["amount"]),
            ("stock", "biz_stock", ["sku", "name", "qty", "safety_qty"], ["qty", "safety_qty"]),
            ("inquiries", "biz_inquiries", ["inquiry_id", "received_at", "channel", "status"], [])]
    for fname, table, cols, ints in spec:
        path = os.path.join(BASE, "seed", fname + ".csv")
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = []
            for r in csv.DictReader(f):
                rows.append([int(r[c]) if c in ints else r[c] for c in cols])
        con.executemany("INSERT INTO %s VALUES (%s)" % (table, ",".join("?" * len(cols))), rows)
    con.commit()
    con.close()


load_db()

ROLE_METRICS = {
    "exec": ["orders", "revenue", "cancel_rate", "stock_alerts", "open_inquiries"],
    "sales": ["orders", "revenue", "cancel_rate", "open_inquiries"],
    "logistics": ["orders", "stock_alerts"],
}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def err(status, detail):
    return JSONResponse({"detail": detail}, status_code=status)


def parse_date(s):
    if not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE, "static", "index.html"))


@app.get("/api/users")
def users():
    con = sqlite3.connect(DB)
    rows = con.execute("SELECT user_id, name, role FROM biz_users ORDER BY rowid").fetchall()
    con.close()
    return [{"user_id": a, "name": b, "role": c} for a, b, c in rows]


def _dashboard(viewer, frm, to):
    if not viewer:
        return err(400, "사용자를 확인하세요")
    today = date.today()
    if frm is None and to is None:
        d_to, d_from = today, today - timedelta(days=6)
    elif frm is None or to is None:
        return err(400, "기간을 확인하세요")
    else:
        d_from, d_to = parse_date(frm), parse_date(to)
        if d_from is None or d_to is None or d_from > d_to or (d_to - d_from).days + 1 > 31:
            return err(400, "기간을 확인하세요")
    con = sqlite3.connect(DB)
    try:
        u = con.execute("SELECT role FROM biz_users WHERE user_id = ?", (viewer,)).fetchone()
        if not u:
            return err(404, "사용자를 찾을 수 없습니다")
        keys = ROLE_METRICS.get(u[0], [])
        f, t = d_from.isoformat(), d_to.isoformat()
        rng = "substr({c}, 1, 10) BETWEEN ? AND ?"
        orders = con.execute("SELECT substr(ordered_at,1,10), customer, amount, status FROM biz_orders WHERE "
                             + rng.format(c="ordered_at"), (f, t)).fetchall()
        total = len(orders)
        cancels = sum(1 for o in orders if o[3] == "취소")
        valid = [o for o in orders if o[3] != "취소"]
        shipped = [o for o in orders if o[3] == "출고"]
        all_m = {
            "orders": len(valid),
            "revenue": sum(o[2] for o in shipped),
            "cancel_rate": None if total == 0 else ((cancels * 2000 + total) // (2 * total)) / 10,
            "stock_alerts": con.execute("SELECT COUNT(*) FROM biz_stock WHERE qty < safety_qty").fetchone()[0],
            "open_inquiries": con.execute("SELECT COUNT(*) FROM biz_inquiries WHERE status IN ('접수','처리중') AND "
                                          + rng.format(c="received_at"), (f, t)).fetchone()[0],
        }
        counts = {}
        for o in valid:
            counts[o[0]] = counts.get(o[0], 0) + 1
        daily = []
        d = d_from
        while d <= d_to:
            daily.append({"date": d.isoformat(), "count": counts.get(d.isoformat(), 0)})
            d += timedelta(days=1)
        body = {"period": {"from": f, "to": t}, "metrics": {k: all_m[k] for k in keys}, "daily": daily}
        if u[0] == "exec":
            rev = {}
            for o in shipped:
                rev[o[1]] = rev.get(o[1], 0) + o[2]
            top = sorted(rev.items(), key=lambda x: (-x[1], x[0]))[:5]
            body["top_customers"] = [{"customer": c, "revenue": r} for c, r in top]
        body["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        return body
    finally:
        con.close()


@app.get("/api/dashboard")
def dashboard(viewer: str = None, frm: str = Query(None, alias="from"), to: str = None):
    return _dashboard(viewer, frm, to)
