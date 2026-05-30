@echo off
chcp 65001 >nul
setlocal EnableExtensions

cd /d "%~dp0"
set "ROOT=%~dp0"
set "ENV_DIR=%ROOT%.pixi\envs\default"
set "PYTHON_EXE=%ENV_DIR%\python.exe"

if not exist "%PYTHON_EXE%" (
  echo [ERROR] Portable Python was not found:
  echo   %PYTHON_EXE%
  echo.
  echo Make sure the portable package includes .pixi\envs\default.
  pause
  exit /b 1
)

set "PATH=%ENV_DIR%;%ENV_DIR%\Scripts;%ENV_DIR%\Library\bin;%ENV_DIR%\Library\usr\bin;%PATH%"
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

"%PYTHON_EXE%" -B "%ROOT%scripts\portable_launcher.py"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Portable launcher exited with code %EXIT_CODE%.
  pause
)

exit /b %EXIT_CODE%
