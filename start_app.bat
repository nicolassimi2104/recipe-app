@echo off
rem Starts the Recipe App and opens it in your browser.
rem The "Recipe App" shortcut runs this (make_shortcut.ps1 creates it).
rem To stop the app, close this window.
title Recipe App
cd /d "%~dp0"

rem Already running? Just open the browser.
netstat -an | findstr /r /c:":5000 .*LISTENING" >nul
if %errorlevel%==0 (
    start "" http://localhost:5000
    exit /b
)

if not exist venv\Scripts\python.exe (
    echo Can't find the venv folder. Set it up first: py -m venv venv
    echo then: venv\Scripts\pip install -r requirements.txt
    pause
    exit /b
)

rem Open the browser in about 3 seconds, once the app has had time to start
start "" /b cmd /c "ping -n 4 127.0.0.1 >nul & start http://localhost:5000"

echo Recipe App is running at http://localhost:5000  (close this window to stop it)
venv\Scripts\python.exe app.py

rem Only reached if the app stops by itself (e.g. an error): keep the message on screen
pause
