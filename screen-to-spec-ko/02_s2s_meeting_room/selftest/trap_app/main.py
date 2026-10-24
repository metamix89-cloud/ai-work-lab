# -*- coding: utf-8 -*-
"""채점기 자가 시험용 함정 앱 — 한 줄 요청으로 흔히 나오는 실수를 일부러 넣었다.
  겹침 검사가 '<=' 라 붙여 예약도 거부(R3) · 30분 단위 검사 없음(R1) · 2시간 상한 없음(R4) · 누구나 취소(R5) · 칸에 data-* 없음(R6).
기대: T1 · T2(td 54칸 폴백) · T4 통과, 나머지 실패 → 3/9."""
import csv
import os

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(HERE, "seed")
app = FastAPI()
RES = []


def rows(name):
    p = os.path.join(SEED, name)
    if not os.path.exists(p):
        return []
    with open(p, encoding="utf-8") as f:
        return [r for r in csv.reader(f)][1:]


for r in rows("reservations.csv"):
    RES.append({"res_id": int(r[0]), "room_id": r[1], "date": r[2], "start": r[3], "end": r[4], "user": r[5]})


class ResIn(BaseModel):
    room_id: str
    date: str
    start: str
    end: str
    user: str


@app.get("/api/reservations")
def reservations(date: str):
    return [r for r in RES if r["date"] == date]


@app.post("/api/reservations", status_code=201)
def create(r: ResIn):
    if r.start < "09:00" or r.end > "18:00":
        raise HTTPException(400, "시간대 밖")
    for x in RES:
        if x["room_id"] == r.room_id and x["date"] == r.date and r.start <= x["end"] and r.end >= x["start"]:
            raise HTTPException(409, "이미 예약된 시간입니다")
    item = dict(r.model_dump(), res_id=max([x["res_id"] for x in RES] + [0]) + 1)
    RES.append(item)
    return item


@app.delete("/api/reservations/{res_id}", status_code=204)
def delete(res_id: int, user: str = ""):
    RES[:] = [x for x in RES if x["res_id"] != res_id]
    return Response(status_code=204)


@app.get("/", response_class=HTMLResponse)
def index(date: str = "2026-11-03"):
    slots = ["%02d:%02d" % (m // 60, m % 60) for m in range(9 * 60, 18 * 60, 30)]
    body = ""
    for room in ("A", "B", "C"):
        body += "<tr><th>%s</th>" % room + "".join("<td>%s</td>" % next((x["user"] for x in RES if x["room_id"] == room and x["date"] == date and x["start"] <= s < x["end"]), "")
                                                    for s in slots) + "</tr>"
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>회의실 예약</title></head><body>
<h1>다온소프트 회의실 예약</h1><select><option>김민수</option><option>박지연</option></select>
<table><thead><tr><th></th>%s</tr></thead><tbody>%s</tbody></table></body></html>""" % ("".join("<th>%s</th>" % s for s in slots), body)
