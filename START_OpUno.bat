@echo off
TITLE Robot OpUno Server (Port 5007)
echo Iniciando Robot OpUno...
echo.
call .venv\Scripts\activate
python robot_opuno\server_opuno.py
pause
