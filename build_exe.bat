@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Build a Windows distribution that does not require Python on the target PC.
set "ROOT=%~dp0"
set "VENV_DIR=%ROOT%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "DIST_DIR=%ROOT%dist\SemaforoIA"

cd /d "%ROOT%"

if not exist "%VENV_PY%" (
    echo [1/4] Creating the virtual environment...
    call :find_python
    if errorlevel 1 exit /b %ERRORLEVEL%
    "!PYTHON_CMD!" !PYTHON_ARGS! -m venv "%VENV_DIR%"
    if errorlevel 1 exit /b %ERRORLEVEL%
)

echo [2/5] Installing or updating dependencies...
"%VENV_PY%" -m pip install --upgrade pip==25.2
if errorlevel 1 exit /b %ERRORLEVEL%
"%VENV_PY%" -m pip install -r "%ROOT%requirements.txt" pyinstaller
if errorlevel 1 exit /b %ERRORLEVEL%

echo [3/5] Building SemaforoIA.exe...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --windowed --onedir ^
    --name "SemaforoIA" ^
    --distpath "%ROOT%dist" ^
    --workpath "%ROOT%build" ^
    --specpath "%ROOT%build" ^
    --paths "%ROOT%export handler" ^
    --hidden-import eco ^
    --hidden-import economia ^
    --hidden-import inicio ^
    --hidden-import config_loader ^
    --add-data "%ROOT%config.json;." ^
    --add-data "%ROOT%data;data" ^
    --add-data "%ROOT%img;img" ^
    --add-data "%ROOT%locales;locales" ^
    --add-data "%ROOT%export handler;export handler" ^
    "%ROOT%main.py"
if errorlevel 1 (
    echo.
    echo BUILD FAILED. Review the PyInstaller output above.
    exit /b %ERRORLEVEL%
)

echo [4/5] Building SemaforoCLI.exe for headless automation...
"%VENV_PY%" -m PyInstaller --noconfirm --clean --console --onefile ^
    --name "SemaforoCLI" ^
    --distpath "%DIST_DIR%" ^
    --workpath "%ROOT%build-cli" ^
    --specpath "%ROOT%build-cli" ^
    "%ROOT%cli.py"
if errorlevel 1 (
    echo.
    echo CLI BUILD FAILED. Review the PyInstaller output above.
    exit /b %ERRORLEVEL%
)

echo [5/5] Preparing the complete distribution...
if not exist "%DIST_DIR%\_internal" (
    echo ERROR: PyInstaller did not create "%DIST_DIR%\_internal".
    echo Run this script again and review the PyInstaller output above.
    exit /b 1
)
dir /b "%DIST_DIR%\_internal\python*.dll" >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python DLL was not found inside "%DIST_DIR%\_internal".
    echo The distribution is incomplete and must not be copied to another PC.
    exit /b 1
)
if not exist "%DIST_DIR%\SemaforoCLI.exe" (
    echo ERROR: Headless executable was not generated.
    exit /b 1
)
if exist "%ROOT%config.json" copy /y "%ROOT%config.json" "%DIST_DIR%\config.json" >nul

echo.
echo BUILD COMPLETE
echo Executable: "%DIST_DIR%\SemaforoIA.exe"
echo Headless CLI: "%DIST_DIR%\SemaforoCLI.exe"
echo Copy the entire "%DIST_DIR%" folder, including _internal, to the target PC.
echo.
exit /b 0

:find_python
set "PYTHON_CMD="
set "PYTHON_ARGS="

if exist "%ROOT%python\python.exe" (
    set "PYTHON_CMD=%ROOT%python\python.exe"
    exit /b 0
)
if exist "%ROOT%Python\python.exe" (
    set "PYTHON_CMD=%ROOT%Python\python.exe"
    exit /b 0
)

where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON_CMD=py"
    set "PYTHON_ARGS=-3"
)
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo ERROR: Python 3 was not found.
    echo Install Python from https://www.python.org/downloads/ or place portable Python in "%ROOT%python\".
    exit /b 1
)
exit /b 0