@echo off
chcp 65001 >nul
title Space Birth Certificate
cd /d "%~dp0"

where python >nul 2>nul
if %errorlevel%==0 (
  python server.py
  goto :end
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py
  goto :end
)
echo [오류] Python을 찾을 수 없습니다. https://www.python.org 에서 Python 3를 설치하세요.

:end
pause
