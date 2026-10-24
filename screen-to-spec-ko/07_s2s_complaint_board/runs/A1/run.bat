@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000
