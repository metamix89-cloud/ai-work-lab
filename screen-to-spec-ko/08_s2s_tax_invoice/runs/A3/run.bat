@echo off
cd /d "%~dp0"
pip install -q fastapi uvicorn
echo http://127.0.0.1:8000
python -m uvicorn main:app --port 8000
