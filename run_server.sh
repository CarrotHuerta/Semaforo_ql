#!/bin/bash
echo "Abriendo puerto 6767 en el Firewall..."
if command -v ufw >/dev/null 2>&1; then
    sudo ufw allow 6767/tcp || echo "[Advertencia] No se pudo abrir el puerto con ufw. Puede que necesites sudo."
elif command -v firewall-cmd >/dev/null 2>&1; then
    sudo firewall-cmd --add-port=6767/tcp || echo "[Advertencia] No se pudo abrir el puerto con firewall-cmd."
else
    echo "[Info] No se detectó ufw o firewall-cmd. Asegurate de que el puerto 6767 este abierto si quieres conexiones externas."
fi

echo "Starting Semáforo IA Server..."
python3 server.py
