@echo off
rem Holt die neueste Version des STL-Schneiders von GitHub.
rem Beim ersten Mal fragt Git nach deiner GitHub-Anmeldung (das Repository ist privat).
setlocal
set ZWEIG=main
set QUELLE=https://github.com/KOLBCRAFT/STL-Schneider.git
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo Git wurde nicht gefunden.
  echo Installiere es mit:  winget install --id Git.Git -e
  echo oder von https://git-scm.com/download/win und starte danach dieses Fenster neu.
  goto fehler
)
if not exist .git (
  echo Richte die Aktualisierung zum ersten Mal ein ...
  git init -q || goto fehler
  git remote add origin %QUELLE% || goto fehler
)
echo Lade die neueste Version ...
git fetch origin %ZWEIG% || goto fehler
git checkout -q -f -B %ZWEIG% origin/%ZWEIG% || goto fehler
echo.
echo Fertig. Aktueller Stand:
git log -1 --format="  %%h  %%cd  %%s" --date=format:"%%d.%%m.%%Y %%H:%%M"
echo.
echo Starte jetzt start.bat. Neue Pakete werden dabei automatisch installiert.
pause
exit /b 0
:fehler
echo.
echo Aktualisierung fehlgeschlagen.
pause
exit /b 1
