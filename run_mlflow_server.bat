@echo off
REM Levanta un MLflow Tracking Server real y local (sqlite backend + artefactos en disco).
REM La UI de Semaforo IA se conecta a este servidor via la Tracking URI configurada en Ajustes.
set MLFLOW_HOME=%~dp0mlflow_data
if not exist "%MLFLOW_HOME%" mkdir "%MLFLOW_HOME%"

REM mlflow vive en el entorno virtual del proyecto, no en el PATH global; lo buscamos
REM en .venv/venv y usamos "python -m mlflow" para no depender del .exe generado.
set PYTHON_EXE=python
if exist "%~dp0.venv\Scripts\python.exe" set PYTHON_EXE=%~dp0.venv\Scripts\python.exe
if exist "%~dp0venv\Scripts\python.exe" set PYTHON_EXE=%~dp0venv\Scripts\python.exe

echo Usando interprete: %PYTHON_EXE%
"%PYTHON_EXE%" -c "import mlflow" 2>nul
if errorlevel 1 (
    echo [Error] El paquete mlflow no esta instalado en ese entorno.
    echo Ejecuta: "%PYTHON_EXE%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo Iniciando MLflow Tracking Server en http://127.0.0.1:5000 ...
"%PYTHON_EXE%" -m mlflow server ^
    --backend-store-uri "sqlite:///%MLFLOW_HOME%/mlflow.db" ^
    --default-artifact-root "%MLFLOW_HOME%/artifacts" ^
    --host 127.0.0.1 ^
    --port 5000
pause

