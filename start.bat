@echo off
rem Startet den KOLBCRAFT Cutter. Beim ersten Start (und nach Updates) wird alles Noetige installiert.
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python wurde nicht gefunden. Bitte von https://www.python.org/downloads/ installieren.
  goto fehler
)
if exist .venv\installiert.txt fc /b requirements.txt .venv\installiert.txt >nul 2>nul && goto starten
echo Richte Python-Umgebung ein, das dauert beim ersten Mal ein paar Minuten ...
if not exist .venv\Scripts\python.exe py -3 -m venv .venv || goto fehler
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || goto fehler
copy /y requirements.txt .venv\installiert.txt >nul
:starten
start "" .venv\Scripts\pythonw.exe gui.py %*
exit /b 0
:fehler
pause
exit /b 1
