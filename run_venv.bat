@echo off
setlocal EnableDelayedExpansion

REM Run the app using a local venv next to this file.
set "ROOT=%~dp0"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_PY%" (
  "%VENV_PY%" -c "import sys" >nul 2>nul
  if errorlevel 1 (
    echo ERROR: The venv looks tied to another user or machine.
    echo Delete "%VENV_DIR%" and run this again.
    exit /b 1
  )
) else (
  echo Venv not found. Creating one...
  call :find_python
  if errorlevel 1 exit /b %ERRORLEVEL%
  "!PYTHON_CMD!" !PYTHON_ARGS! -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b %ERRORLEVEL%
)

REM Install deps if needed.
if exist "%ROOT%requirements.txt" (
  "%VENV_PY%" -m pip install --upgrade pip
  "%VENV_PY%" -m pip install -r "%ROOT%requirements.txt"
) else (
  "%VENV_PY%" -m pip install --upgrade pip
  "%VENV_PY%" -m pip install PySide6
)

"%VENV_PY%" "%ROOT%main.py"

endlocal
exit /b %ERRORLEVEL%

:find_python
set "PYTHON_CMD="
set "PYTHON_ARGS="

REM Prefer a portable Python shipped with the project.
if exist "%ROOT%python\python.exe" (
  set "PYTHON_CMD=%ROOT%python\python.exe"
  exit /b 0
)
if exist "%ROOT%Python\python.exe" (
  set "PYTHON_CMD=%ROOT%Python\python.exe"
  exit /b 0
)

where py >nul 2>nul && set "PYTHON_CMD=py" && set "PYTHON_ARGS=-3"
if not defined PYTHON_CMD (
  where python >nul 2>nul && set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
  for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
    if not defined PYTHON_CMD if exist "%%~fD\python.exe" set "PYTHON_CMD=%%~fD\python.exe"
  )
)
if not defined PYTHON_CMD (
  for /d %%D in ("%ProgramFiles%\Python*") do (
    if not defined PYTHON_CMD if exist "%%~fD\python.exe" set "PYTHON_CMD=%%~fD\python.exe"
  )
)
if not defined PYTHON_CMD (
  for /d %%D in ("%ProgramFiles(x86)%\Python*") do (
    if not defined PYTHON_CMD if exist "%%~fD\python.exe" set "PYTHON_CMD=%%~fD\python.exe"
  )
)
if not defined PYTHON_CMD (
  echo ERROR: Python 3 not found.
  echo Install Python from https://www.python.org/downloads/ ^(check "Add Python to PATH"^).
  echo Or place a portable Python in "%ROOT%python\python.exe".
  exit /b 1
)
exit /b 0
