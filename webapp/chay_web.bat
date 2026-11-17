@echo off
rem GATE VISION - bam doi file nay de chay web (Windows).
rem Doi GV_DEV thanh 0 neu muon chay that (khong co du lieu mau, khong co cong cu thu).
set GV_DEV=1
set PORT=8000

cd /d "%~dp0"
title GATE VISION server

set PYCMD=
where py >nul 2>nul && set PYCMD=py
if not defined PYCMD (
  where python >nul 2>nul && set PYCMD=python
)
if not defined PYCMD (
  echo Khong tim thay Python. Hay cai Python 3.10 tro len tu https://www.python.org/downloads/
  echo va tick "Add python.exe to PATH" khi cai.
  pause
  exit /b 1
)

%PYCMD% -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Dang cai thu vien lan dau, doi mot chut...
  %PYCMD% -m pip install -r server\requirements.txt
  if errorlevel 1 (
    echo Cai thu vien that bai. Kiem tra ket noi mang roi chay lai.
    pause
    exit /b 1
  )
)

echo.
echo Server dang chay tai http://localhost:%PORT%  (bam Ctrl+C de tat)
echo.
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:%PORT%"
%PYCMD% -m uvicorn server.main:app --port %PORT%

echo.
echo Server da dung. Neu thay loi o tren, chup man hinh gui lai.
pause
