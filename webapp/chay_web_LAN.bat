@echo off
rem GATE VISION - chay web cho may khac trong cung mang LAN truy cap (dien thoai, may khac).
rem Chi dung trong mang rieng: giao thuc HTTP, khong ma hoa.
set GV_DEV=1
set PORT=8000

cd /d "%~dp0"
title GATE VISION server (LAN)

set PYCMD=
where py >nul 2>nul && set PYCMD=py
if not defined PYCMD (
  where python >nul 2>nul && set PYCMD=python
)
if not defined PYCMD (
  echo Khong tim thay Python. Hay cai Python 3.10 tro len.
  pause
  exit /b 1
)

%PYCMD% -c "import fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Dang cai thu vien lan dau, doi mot chut...
  %PYCMD% -m pip install -r server\requirements.txt
)

echo.
echo Cac dia chi IP cua may nay (dung dia chi IPv4 cua mang Wi-Fi/LAN):
ipconfig | findstr /i "IPv4"
echo.
echo Tren dien thoai/may khac cung mang, mo:  http://^<dia-chi-IPv4^>:%PORT%
echo Neu Windows hoi ve Firewall, chon "Allow access" cho mang rieng (Private).
echo Bam Ctrl+C de tat.
echo.
%PYCMD% -m uvicorn server.main:app --host 0.0.0.0 --port %PORT%

echo.
pause
