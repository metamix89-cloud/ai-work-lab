import uvicorn

uvicorn.run("main:app", app_dir="app", host="127.0.0.1", port=8000)
