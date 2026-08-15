@echo off
echo Abriendo puerto 6767 en el Firewall de Windows...
netsh advfirewall firewall add rule name="Semaforo IA Server" dir=in action=allow protocol=TCP localport=6767 >nul 2>&1
if %errorlevel% neq 0 (
    echo [Advertencia] No se pudo abrir el puerto automaticamente. Es posible que necesite ejecutar esto como Administrador.
) else (
    echo [OK] Puerto 6767 abierto.
)

echo Activando entorno virtual...
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo [Advertencia] No se encontro venv\Scripts\activate.bat. Asegurate de tener el entorno virtual creado.
)

echo Starting Semáforo IA Server...
python server.py
pause
