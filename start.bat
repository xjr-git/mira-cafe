@echo off
rem ASCII-only on purpose (GBK-safe). One-command local start for Windows.
setlocal
cd /d "%~dp0"

set "PY_AUTO="
if exist "D:\miniconda\envs\llm\python.exe" set "PY_AUTO=D:\miniconda\envs\llm\python.exe"
if not defined PY_AUTO if exist "D:\miniconda\python.exe" set "PY_AUTO=D:\miniconda\python.exe"
if not defined PY_AUTO if exist "C:\Users\User\miniconda3\python.exe" set "PY_AUTO=C:\Users\User\miniconda3\python.exe"
if not defined PY_AUTO set "PY_AUTO=python"
set "PY=%PY_AUTO%"

if not exist ".venv" (
  echo [1/3] creating venv with %PY% ...
  "%PY%" -m venv .venv
)

echo [2/3] installing dependencies ...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
  echo pip install failed - check network or run: .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo [3/3] starting server ...
echo.
echo   Mock mode: no API key needed - the scripted story brain runs.
echo   Full mode: copy .env.example to .env and fill DASHSCOPE_API_KEY.
echo   URL: http://127.0.0.1:8000/
echo.

start "" http://127.0.0.1:8000/
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
