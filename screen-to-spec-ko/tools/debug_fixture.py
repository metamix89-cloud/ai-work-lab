# -*- coding: utf-8 -*-
"""채점 때만 서버가 죽는 앱을 조사한다 — 앱 폴더를 임시 폴더로 복사하고, 그 편 테스트의 고정 데이터(write_seed)를 넣은 뒤
uvicorn 을 띄워 출력(오류)을 그대로 보여 준다. 원본 runs/ 폴더는 건드리지 않는다.
사용: python _scratch/s2s/tools/debug_fixture.py <app_dir> <lab_dir> [port]"""
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
app_src = os.path.abspath(sys.argv[1])
lab = os.path.abspath(sys.argv[2])
port = int(sys.argv[3]) if len(sys.argv) > 3 else 8896
work = os.path.join(tempfile.mkdtemp(), "app")
shutil.copytree(app_src, work, ignore=shutil.ignore_patterns("_grader", "__pycache__", "*.db"))
os.environ["APP_DIR"] = work
spec = importlib.util.spec_from_file_location("dod", os.path.join(lab, "tests", "test_dod.py"))
dod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dod)
dod.write_seed()
target, _ = dod.find_app_target()
print("앱:", target, "| 작업 폴더:", work)
env = dict(os.environ, PORT=str(port), PYTHONUTF8="1")
p = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--port", str(port)], cwd=work, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
time.sleep(6)
if p.poll() is None:
    p.kill()
out = p.communicate(timeout=10)[0].decode("utf-8", "ignore")
print("종료 코드:", p.returncode)
print(out[-3000:])
shutil.rmtree(os.path.dirname(work), ignore_errors=True)
