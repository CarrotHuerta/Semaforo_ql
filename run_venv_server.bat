@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"

echo Abriendo puerto 6767 en el Firewall de Windows...
netsh advfirewall firewall add rule name="Semaforo IA Server" dir=in action=allow protocol=TCP localport=6767 >nul 2>&1
if errorlevel 1 (
    echo [Advertencia] No se pudo abrir el puerto automaticamente. Es posible que necesite ejecutar esto como Administrador.
) else (
    echo [OK] Puerto 6767 abierto.
)

if not exist "%VENV_PY%" (
    echo [ERROR] No se encontro el entorno virtual en "%ROOT%.venv".
    echo Ejecuta run_venv.bat una vez para crearlo e instalar las dependencias.
    pause
    exit /b 1
)

"%VENV_PY%" -c "import cryptography" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias faltantes en .venv...
    "%VENV_PY%" -m pip install -r "%ROOT%requirements.txt"
    if errorlevel 1 (
        echo [ERROR] No se pudieron instalar las dependencias.
        pause
        exit /b 1
    )
)

echo Iniciando Semaforo IA Server con .venv...
"%VENV_PY%" "%ROOT%server.py"
set "SERVER_EXIT=%ERRORLEVEL%"
if not "%SERVER_EXIT%"=="0" echo [ERROR] El servidor termino con codigo %SERVER_EXIT%.
pause
endlocal & exit /b %SERVER_EXIT%
