@echo off
TITLE Simple Pump Robot Server (Port 5010)
echo Iniciando Simple Pump Robot...
echo.
call .venv\Scripts\activate
python simple_pump_robot\server_pump.py
pause
