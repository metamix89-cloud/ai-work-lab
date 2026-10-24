# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수를 일부러 넣었다.
  일수를 달력일로 셈(주말 포함, R1) · 잔여 = 총 − 승인만(대기 안 뺌, R2) · 누구나 승인(R3) · 반려 사유 선택(R4) · 재승인 허용(R5) · 겹침 검사 없음(R6)
  · 화면에 remaining · pending-request 손잡이 없음.
기대: T1 만 통과 → 1/9. (T4 는 잔여를 '총 − 승인 = 13' 으로 세어 10일 연차를 통과시키므로 실패)"""
import csv
import datetime as dt
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
app = FastAPI()
USERS, REQS = [], []


def rows(name):
    p = os.path.join(SEED, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [r for r in csv.reader(f)][1:]


for r in rows("users.csv"):
    USERS.append({"user": r[0], "team": r[1], "role": r[2], "manager": r[3], "leave_total": int(r[4])})
for r in rows("requests.csv"):
    REQS.append({"req_id": int(r[0]), "user": r[1], "type": r[2], "start": r[3], "end": r[4], "days": int(r[5]),
                 "reason": r[6], "status": r[7], "approver": r[8], "reject_reason": r[9]})


class ReqIn(BaseModel):
    user: str
    type: str
    start: str
    end: str
    reason: str = ""


class Approver(BaseModel):
    approver: str
    reason: str = ""


class Who(BaseModel):
    user: str


@app.get("/api/users")
def users():
    return USERS


@app.get("/api/balance")
def balance(user: str):
    u = next(x for x in USERS if x["user"] == user)
    used = sum(r["days"] for r in REQS if r["user"] == user and r["type"] == "연차" and r["status"] == "승인")
    return {"total": u["leave_total"], "used": used, "pending": 0, "remaining": u["leave_total"] - used}


@app.get("/api/requests")
def requests(user: str = "", approver: str = ""):
    if user:
        return [r for r in REQS if r["user"] == user]
    return [r for r in REQS if r["status"] == "신청"]


@app.post("/api/requests", status_code=201)
def create(r: ReqIn):
    days = (dt.date.fromisoformat(r.end) - dt.date.fromisoformat(r.start)).days + 1
    if r.type == "연차" and days > balance(r.user)["remaining"]:
        raise HTTPException(400, "잔여 연차가 부족합니다")
    item = dict(r.model_dump(), req_id=max([x["req_id"] for x in REQS] + [0]) + 1, days=days, status="신청", approver="", reject_reason="")
    REQS.append(item)
    return item


@app.post("/api/requests/{req_id}/approve")
def approve(req_id: int, a: Approver):
    row = next(x for x in REQS if x["req_id"] == req_id)
    row.update(status="승인", approver=a.approver)
    return row


@app.post("/api/requests/{req_id}/reject")
def reject(req_id: int, a: Approver):
    row = next(x for x in REQS if x["req_id"] == req_id)
    row.update(status="반려", approver=a.approver, reject_reason=a.reason)
    return row


@app.post("/api/requests/{req_id}/cancel")
def cancel(req_id: int, w: Who):
    row = next(x for x in REQS if x["req_id"] == req_id)
    row.update(status="취소")
    return row


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>휴가 신청</title></head><body>
<h1>다온소프트 휴가 · 출장 신청</h1><select data-testid="user-select"><option>김민수</option><option>박지연</option></select>
<p>잔여 연차: 12일</p><ul><li>연차 10-12~10-13 승인</li></ul></body></html>"""
