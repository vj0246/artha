@echo off
rem Scheduled monthly research refresh (Track E E3): agent screens + SPA.
cd /d "C:\Users\vivaa\OneDrive\Desktop\Personal Projects\Quant\artha"
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.local\bin\uv.exe" run --no-sync python scripts\run_research_agent.py --offline >> "%USERPROFILE%\quant-data\reports\paper\cycle.log" 2>&1
"%USERPROFILE%\.local\bin\uv.exe" run --no-sync python scripts\run_spa.py >> "%USERPROFILE%\quant-data\reports\paper\cycle.log" 2>&1
