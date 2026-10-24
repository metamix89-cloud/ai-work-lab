@echo off
cd /d %~dp0app
python -m uvicorn main:app --port 8000
