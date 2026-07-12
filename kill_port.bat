@echo off
echo Killing process on port 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo Done. Starting app...
python app.py