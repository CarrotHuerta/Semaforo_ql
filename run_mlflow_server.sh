#!/bin/bash
# Levanta un MLflow Tracking Server real y local (sqlite backend + artefactos en disco).
# La UI de Semaforo IA se conecta a este servidor via la Tracking URI configurada en Ajustes.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MLFLOW_HOME="${SCRIPT_DIR}/mlflow_data"
mkdir -p "$MLFLOW_HOME"

# mlflow vive en el entorno virtual del proyecto, no en el PATH global; lo buscamos
# en .venv/venv y usamos "python -m mlflow" para no depender de que el script este en PATH.
PYTHON_BIN="python3"
if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
    PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
elif [ -x "${SCRIPT_DIR}/venv/bin/python" ]; then
    PYTHON_BIN="${SCRIPT_DIR}/venv/bin/python"
fi

echo "Usando interprete: ${PYTHON_BIN}"
if ! "$PYTHON_BIN" -c "import mlflow" 2>/dev/null; then
    echo "[Error] El paquete mlflow no esta instalado en ese entorno."
    echo "Ejecuta: ${PYTHON_BIN} -m pip install -r requirements.txt"
    exit 1
fi

echo "Iniciando MLflow Tracking Server en http://127.0.0.1:5000 ..."
"$PYTHON_BIN" -m mlflow server \
    --backend-store-uri "sqlite:///${MLFLOW_HOME}/mlflow.db" \
    --default-artifact-root "${MLFLOW_HOME}/artifacts" \
    --host 127.0.0.1 \
    --port 5000

