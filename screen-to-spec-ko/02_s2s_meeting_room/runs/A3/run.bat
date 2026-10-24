@echo off
pip install -r requirements.txt
python -m uvicorn main:app --port 8000
