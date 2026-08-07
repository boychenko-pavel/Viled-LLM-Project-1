@echo off
setlocal
set "PROJECT_DIR=C:\Users\p.boychenko\Desktop\MachineLearning\Viled ATLAS LLM Project"
cd /d "%PROJECT_DIR%"

set "PROJECT_PYTHON=%PROJECT_DIR%\.venv\Scripts\python.exe"

if not exist "%PROJECT_PYTHON%" (
    echo Project virtual environment was not found:
    echo %PROJECT_PYTHON%
    pause
    exit /b 1
)

echo Starting Viled ATLAS at http://127.0.0.1:8000
"%PROJECT_PYTHON%" -m uvicorn sql_agent.web:app --host 127.0.0.1 --port 8000

if errorlevel 1 (
    echo.
    echo Server stopped with an error.
    pause
)
