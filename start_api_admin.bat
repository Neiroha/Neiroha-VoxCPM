@echo off
cd /d "%~dp0"

where pixi >nul 2>nul
if errorlevel 1 (
  echo Pixi is required. Install Pixi first, then rerun this script.
  exit /b 1
)

if not exist ".pixi\envs\default" (
  pixi install
)

pixi run serve %*
