@echo off
title Stock Picker Portfolio Update
echo Fetching latest prices for HyperGrowth Sharpe Barbell...
cd /d "%~dp0"
python update.py
echo.
echo Done. Now open or refresh index.html in your browser.
echo.
pause
