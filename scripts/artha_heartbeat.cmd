@echo off
rem Nightly operational heartbeat (Track G): catches a cycle that never ran.
cd /d "C:\Users\vivaa\OneDrive\Desktop\Personal Projects\Quant\artha"
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.local\bin\uv.exe" run --no-sync python scripts\run_heartbeat.py >> "%USERPROFILE%\quant-data\reports\paper\cycle.log" 2>&1
