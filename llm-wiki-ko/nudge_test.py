# -*- coding: utf-8 -*-
"""5편 v3 `--require-write` 자가 시험: 모델이 write_page 없이 보고문만 내면 한 번 재촉하고, 재촉 뒤 쓰기가 들어오면 페이지가 저장되는지.
API 호출 없음 — engine.chat 을 가짜 응답 순서로 바꿔 돈다. 사용: python _scratch/wiki/nudge_test.py"""
import json, os, shutil, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine as E
sys.stdout.reconfigure(encoding="utf-8")


class Fn:
    def __init__(self, name, args): self.name, self.arguments = name, json.dumps(args, ensure_ascii=False)


class TC:
    def __init__(self, i, name, args): self.id, self.function = "c%d" % i, Fn(name, args)


class Msg:
    def __init__(self, content=None, calls=None):
        self.content, self.tool_calls, self.role = content, calls, "assistant"


def fake_chat_factory(script):
    it = iter(script)
    def chat(msgs, tools=None, temp=0.3):
        if msgs[-1].get("role") == "user" and msgs[-1]["content"] == E.NUDGE_WRITE:
            chat.nudges += 1
        return next(it), 100
    chat.nudges = 0
    return chat


wdir = tempfile.mkdtemp(prefix="nudge_")
w = E.Wiki(wdir, schema_path=os.path.join(E.HERE, "schema_ep5.md"))
w.write_page("규정/18-보안", "# 18. 보안\n분류: 규정\n\n## 현재 값\n- 거래처 단가 금지")
fails = 0

# (1) 보고문만 → 재촉 → write_page → 보고문. 페이지가 바뀌어야 한다.
script = [Msg("보고: 18조를 고쳤다(라고만 말함)"),
          Msg(None, [TC(1, "write_page", dict(slug="규정/18-보안", content="# 18. 보안\n분류: 규정\n\n## 현재 값\n- 거래처 단가는 구매팀장 승인 시 허용"))]),
          Msg("보고: 저장 완료")]
E.chat = fake_chat_factory(script)
ans, tok, trace = E.run_agent(w, "sys", "user", E.TOOLS_RW, 10, guard=(9, False), require_write=True)
ok = E.chat.nudges == 1 and "구매팀장" in (w.read_page("규정/18-보안") or "") and ans == "보고: 저장 완료" and ("nudge", "require_write") in trace
print("1 재촉 뒤 저장      ", "통과" if ok else "실패", "| nudges=%d trace=%s" % (E.chat.nudges, [n for n, _ in trace]))
fails += not ok

# (2) 재촉에도 또 보고문만 → 두 번 재촉하지 않고 끝낸다.
w.write_page("규정/18-보안", "# 18. 보안\n분류: 규정\n\n## 현재 값\n- 거래처 단가 금지")
E.chat = fake_chat_factory([Msg("보고만 1"), Msg("보고만 2"), Msg("보고만 3 — 여기까지 오면 안 됨")])
ans, tok, trace = E.run_agent(w, "sys", "user", E.TOOLS_RW, 10, guard=(9, False), require_write=True)
ok = E.chat.nudges == 1 and ans == "보고만 2"
print("2 재촉은 한 번만     ", "통과" if ok else "실패", "| nudges=%d ans=%s" % (E.chat.nudges, ans))
fails += not ok

# (3) 처음부터 write_page 를 했으면 재촉 없음.
E.chat = fake_chat_factory([Msg(None, [TC(1, "write_page", dict(slug="규정/18-보안", content="# 18. 보안\n분류: 규정\n\n## 현재 값\n- x"))]), Msg("보고"), Msg("안 와야 함")])
ans, tok, trace = E.run_agent(w, "sys", "user", E.TOOLS_RW, 10, guard=(9, False), require_write=True)
ok = E.chat.nudges == 0 and ans == "보고"
print("3 썼으면 재촉 없음   ", "통과" if ok else "실패", "| nudges=%d" % E.chat.nudges)
fails += not ok

# (4) require_write=False(ep5b 조건)면 예전과 같이 보고문으로 바로 끝난다.
E.chat = fake_chat_factory([Msg("보고만"), Msg("안 와야 함")])
ans, tok, trace = E.run_agent(w, "sys", "user", E.TOOLS_RW, 10, guard=(9, False), require_write=False)
ok = E.chat.nudges == 0 and ans == "보고만"
print("4 옵션 꺼짐 = 옛 동작", "통과" if ok else "실패")
fails += not ok

# (5) 재촉 뒤 새 페이지를 만들려 하면 여전히 거부(가드 9) → 모델이 다시 쓰기 → 저장.
E.chat = fake_chat_factory([Msg("보고만"),
                            Msg(None, [TC(1, "write_page", dict(slug="규정/18-보안-보완", content="새 페이지"))]),
                            Msg(None, [TC(2, "write_page", dict(slug="규정/18-보안", content="# 18\n- 구매팀장 승인 시 허용"))]),
                            Msg("끝")])
ans, tok, trace = E.run_agent(w, "sys", "user", E.TOOLS_RW, 10, guard=(9, False), require_write=True)
ok = w.read_page("규정/18-보안-보완") is None and "구매팀장" in w.read_page("규정/18-보안") and ans == "끝"
print("5 재촉 뒤에도 가드 유지", "통과" if ok else "실패")
fails += not ok

shutil.rmtree(wdir, ignore_errors=True)
print("\n%s (%d 실패)" % ("모두 통과" if not fails else "실패 있음", fails))
sys.exit(1 if fails else 0)
