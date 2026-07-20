@echo off
rem Scheduled quarterly construction re-validation (Track E E3).
cd /d "C:\Users\vivaa\OneDrive\Desktop\Personal Projects\Quant\artha"
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.local\bin\uv.exe" run --no-sync python scripts\run_construction_v2.py >> "%USERPROFILE%\quant-data\reports\paper\cycle.log" 2>&1
"%USERPROFILE%\.local\bin\uv.exe" run --no-sync python scripts\run_spa.py >> "%USERPROFILE%\quant-data\reports\paper\cycle.log" 2>&1
