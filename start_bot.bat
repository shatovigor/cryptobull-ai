@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ОШИБКА] Папка venv не найдена!
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python gui_auto.py

if errorlevel 1 (
    echo.
    echo [ОШИБКА] Программа завершилась с ошибкой.
    pause
)