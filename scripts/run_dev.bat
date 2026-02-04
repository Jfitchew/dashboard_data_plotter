@echo off
setlocal

cd /d "%~dp0\.."

REM Optional: create venv if missing
if not exist ".venv\Scripts\python.exe" (
  echo Creating venv in .venv ...
  py -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python main.py

endlocal
