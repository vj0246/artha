@echo off
rem Scheduled entrypoint for the daily paper cycle (Track B B1).
cd /d "C:\Users\vivaa\OneDrive\Desktop\Personal Projects\Quant\artha"
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.local\bin\uv.exe" run --no-sync python scripts\run_daily_cycle.py >> "%USERPROFILE%\quant-data\reports\paper\cycle.log" 2>&1
