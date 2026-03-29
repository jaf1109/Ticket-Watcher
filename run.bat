@echo off
echo Starting CineplexBD Ticket Watcher...
echo Dashboard will open at http://localhost:8080
echo.
start /B pythonw "%~dp0src\service.py"
timeout /t 2 /nobreak > nul
start http://localhost:8080
echo Watcher is running in the background.
echo To stop, close from Task Manager or run: taskkill /f /im pythonw.exe
