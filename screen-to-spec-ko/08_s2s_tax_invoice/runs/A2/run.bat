@echo off
cd /d %~dp0
echo http://localhost:8000
python -m uvicorn main:app --port 8000
