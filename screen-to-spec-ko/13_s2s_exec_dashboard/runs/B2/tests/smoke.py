import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

import main

with TestClient(main.app) as c:
    def g(**q):
        return c.get("/api/dashboard", params=q)

    P = {"from": "2026-10-18", "to": "2026-10-24"}
    r = g(viewer="u1", **P).json()
    print(r)
    assert r["metrics"] == {"orders": 8, "revenue": 600000, "cancel_rate": 27.3, "stock_alerts": 2, "open_inquiries": 3}
    assert len(r["daily"]) == 7
    print(g(viewer="u3", **P).json())
    print(g(viewer="u2", **P).json())
    for q in [dict(viewer="u1", **{"from": "2026-10-24", "to": "2026-10-18"}),
              dict(viewer="u1", **{"from": "2026-09-01", "to": "2026-10-02"}),
              dict(viewer="u1", **{"from": "2026-10-18"}),
              dict(**{"from": "x", "to": "y"}), dict(viewer="zz")]:
        x = g(**q)
        print(x.status_code, x.json())
    print(g(viewer="zz", **P).status_code)
    print(g(viewer="u1", **{"from": "2026-01-01", "to": "2026-01-03"}).json())
    print(g(viewer="u1").status_code)
