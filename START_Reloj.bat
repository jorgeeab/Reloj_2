@echo off
TITLE Robot Reloj Server (Port 5005)
echo Iniciando Robot Reloj...
echo.
call .venv\Scripts\activate
python robot_reloj\server_reloj.py
pause
