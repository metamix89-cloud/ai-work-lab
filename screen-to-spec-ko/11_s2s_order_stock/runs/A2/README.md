# 가나다식품 주문·재고 백오피스

FastAPI + SQLite + 순수 HTML/JS.

## 실행
```
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
```
http://localhost:8000 접속. 최초 실행 시 `ganada.db`가 만들어지고 가상 데이터가 들어갑니다 (초기화: `ganada.db*` 삭제).

데모 계정: `staff / staff123` (직원), `admin / admin123` (관리자)

## 재고 규칙
| 동작 | 가능 상태 | 재고 |
|---|---|---|
| 확정 | 접수 | 차감 (하나라도 부족하면 전체 실패) |
| 출고 | 확정 | 변화 없음 |
| 취소 | 접수, 확정 | 확정 상태였다면 복원 |
| 환불 (관리자) | 출고 | 반품 재입고 체크 시 복원 |
| 재고 조정 (관리자) | - | 0 미만 불가 |

- `products.stock >= 0` CHECK 제약 + `UPDATE ... WHERE stock >= qty` 조건부 차감.
- 상태 전이는 `UPDATE ... WHERE status = 기대상태`로 선점 → 더블클릭/동시 요청에도 이중 차감·복원 없음.
- 모든 재고 증감은 `stock_movements`에 기록 (재고 이력 탭).

## 테스트
`python -m pytest -q` (동시 확정 시 초과 판매 없음, 동시 취소 시 1회만 복원 등)
