@echo off
rem Scheduled entrypoint for the weekly live-vs-research review (Track B B1).
cd /d "C:\Users\vivaa\OneDrive\Desktop\Personal Projects\Quant\artha"
set PYTHONIOENCODING=utf-8
"%USERPROFILE%\.local\bin\uv.exe" run --no-sync python scripts\run_weekly_review.py >> "%USERPROFILE%\quant-data\reports\paper\cycle.log" 2>&1
