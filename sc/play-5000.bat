@echo off
cd /d "%~dp0"

python player3.py
pause
:: Wait 2 seconds to ensure the server is ready  timeout /t 2 /nobreak >nul


:: Open the web app using the specified Edge browser executable
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" http://127.0.0.1:5000

:: Optional: Uncomment the line below if you want to keep the console window open for debugging
pause