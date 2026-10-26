@echo off
rem Startet den STL-Schneider. Beim ersten Start wird alles Noetige installiert.
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python wurde nicht gefunden. Bitte von https://www.python.org/downloads/ installieren.
  goto fehler
)
if exist .venv\installiert.txt goto starten
echo Erster Start: richte Python-Umgebung ein ...
if exist .venv rmdir /s /q .venv
py -3 -m venv .venv || goto fehler
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto fehler
echo ok> .venv\installiert.txt
:starten
start "" .venv\Scripts\pythonw.exe gui.py
exit /b 0
:fehler
if exist .venv rmdir /s /q .venv
pause
exit /b 1
