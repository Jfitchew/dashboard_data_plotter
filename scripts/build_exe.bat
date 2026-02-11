@echo off
setlocal

cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  echo Creating venv in .venv ...
  py -m venv .venv
)

call ".venv\Scripts\activate.bat"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install pyinstaller

REM Clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist DashboardDataPlotter.spec del /q DashboardDataPlotter.spec

REM Build one-file windowed exe (include assets + docs)
pyinstaller --clean --noconfirm --windowed --onefile --name DashboardDataPlotter --paths src --add-data "src\dashboard_data_plotter\assets;dashboard_data_plotter\assets" --add-data "GUIDE.md;." --add-data "CHANGELOG.md;." main.py


echo.
echo Built: dist\DashboardDataPlotter.exe
endlocal
