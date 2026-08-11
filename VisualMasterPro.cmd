@echo off
setlocal
cd /d "%~dp0"
set "HDDE_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%HDDE_PYTHON%" (
  echo HDDE startup failed: project runtime is missing.
  echo Required interpreter: %HDDE_PYTHON%
  exit /b 1
)
"%HDDE_PYTHON%" -m runtime.formal_launcher %*
exit /b %errorlevel%
