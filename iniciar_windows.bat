@echo off
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo No fue posible iniciar la aplicacion. Verifica que Python 3 este instalado.
  pause
)
