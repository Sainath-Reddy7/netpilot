@echo off
REM NetPilot background collector: monitors continuously and live-syncs
REM the website. Launched silently via the Startup folder (netpilot-collector.vbs).
REM
REM To stop it:        Task Manager -> pythonw.exe -> End task
REM To remove startup: delete netpilot-collector.vbs from the Startup folder
REM
cd /d "%~dp0.."
start "" /b "C:\Users\bsain\AppData\Local\Programs\Python\Python313\pythonw.exe" netpilot.py --sync --headless --interval 10
