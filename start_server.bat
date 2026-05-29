@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: 寻找 Python（含 Anaconda 路径）
set PYTHON=
for %%p in (
    python
    python3
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%USERPROFILE%\miniconda3\python.exe"
    "C:\ProgramData\anaconda3\python.exe"
) do (
    if "!PYTHON!"=="" (
        where /q %%p 2>nul
        if !errorlevel!==0 set PYTHON=%%p
        if exist "%%p" set PYTHON="%%p"
    )
)

if "%PYTHON%"=="" (
    echo [ERROR] Python not found. Please install Python 3.
    pause
    exit /b 1
)

echo Using Python: %PYTHON%
echo Starting 寻迹故宫 server on http://127.0.0.1:8000
echo Report mode: http://127.0.0.1:8000/?report=1
echo.

%PYTHON% backend\server.py
pause
