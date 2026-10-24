# 가나다식품 세금계산서

```
pip install fastapi uvicorn
python main.py        # http://127.0.0.1:8000
```

- 첫 실행 시 `invoices.db`가 생성되고 가상 거래처 6곳 / 계산서 12건이 들어갑니다. (초기화: `invoices.db` 삭제)
- 세액 = 과세 품목 공급가액 × 10% (원 단위 절사), 면세 품목은 0원. 서버(`main.py calc`)가 최종 계산합니다.
- 국세청 전송 기능은 없습니다.
