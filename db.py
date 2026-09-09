import csv
import os
import sqlite3

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover - graceful fallback for minimal environments
    psycopg2 = None
    psycopg2_extras = None

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "greenops"),
    "user": os.environ.get("DB_USER", "jules"),
    "password": os.environ.get("DB_PASSWORD", "password"),
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432")
}

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _sqlite_path():
    path = os.environ.get("DB_PATH", os.path.join(_BASE_DIR, "semaforo.sqlite3"))
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    return path


def _csv_fallback_rows(table_name):
    csv_map = {
        "hardware_csv": "hardware.csv",
        "intensidad_carbono_csv": "intensidad_carbono.csv",
        "modelos_ia_csv": "modelos_ia.csv",
    }
    path = os.path.join(_BASE_DIR, "data", csv_map.get(table_name, ""))
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return list(reader)
    except (OSError, csv.Error):
        return []


def get_connection():
    mode = str(os.environ.get("DB_MODE", "sqlite")).strip().lower()
    if mode == "postgres" and psycopg2 is not None:
        try:
            return psycopg2.connect(**DB_CONFIG)
        except Exception:
            pass
    return sqlite3.connect(_sqlite_path())


def load_db_rows(table_name):
    try:
        with get_connection() as conn:
            if isinstance(conn, sqlite3.Connection):
                return _csv_fallback_rows(table_name)
            cursor_factory = getattr(psycopg2.extras, "DictCursor", None)
            if cursor_factory is None:
                return _csv_fallback_rows(table_name)
            with conn.cursor(cursor_factory=cursor_factory) as cursor:
                cleaned_rows = []

                if table_name == "hardware_csv":
                    cursor.execute("SELECT * FROM componente_hardware")
                    rows = cursor.fetchall()
                    for r in rows:
                        cleaned_rows.append({
                            'ID_Hardware': f"HW_{r['id_componente']:03d}",
                            'Fabricante': r['fabricante'] or '',
                            'Modelo': r['modelo_hw'] or r['etiqueta_hardware'],
                            'Categoria': r['categoria_hardware'],
                            'Arquitectura_Anio': r['arquitectura_anio'] or '',
                            'VRAM_GB': r['vram_gb'] or '',
                            'Ancho_Banda_GBs': r['ancho_banda_gbs'] or '',
                            'TDP_Max_Watts': str(r['tdp_estandar_watts']),
                            'FP16_FP32_TFLOPS': r['fp16_fp32_tflops'] or '',
                            'Eficiencia_Tokens_Watt': r['eficiencia_tokens_watt'] or '',
                            'Huella_CO2e_kg': r['huella_co2e_kg'] or ''
                        })

                elif table_name == "intensidad_carbono_csv":
                    cursor.execute("SELECT * FROM region_geografica")
                    rows = cursor.fetchall()
                    for r in rows:
                        cleaned_rows.append({
                            'ID_Region': f"REG_{r['id_region']:03d}",
                            'Region_Pais_Ubicacion': r['nombre_region'],
                            'Entorno_Ejecucion': r['entorno_ejecucion'] or r['proveedor_cloud'] or 'Datacenter Local / Cloud',
                            'Intensidad_Carbono_gCO2eq_kWh': str(r['factor_emision_gco2eq']),
                            'PUE_Promedio': r['pue_promedio'] or '1.0',
                            'Nivel_Dano_Ambiental': r['nivel_dano_ambiental'] or 'Calculado'
                        })

                elif table_name == "modelos_ia_csv":
                    cursor.execute("SELECT * FROM modelo")
                    rows = cursor.fetchall()
                    for r in rows:
                        cleaned_rows.append({
                            'ID_Modelo': f"MOD_{r['id_modelo']:03d}",
                            'Nombre_Modelo': r['nombre_modelo'],
                            'Empresa_Creador': r['empresa_creador'] or '',
                            'Dominio': r['descripcion_contexto'] or 'N/A',
                            'Parametros_Billones': r['parametros_billones'] or 'N/A',
                            'VRAM_Minima_GB_FP16_INT8': r['vram_minima_gb_fp16_int8'] or 'N/A',
                            'Consumo_Energetico_Base': r['consumo_energetico_base'] or 'N/A',
                            'Unidad_Medida': r['unidad_medida'] or 'N/A',
                            'Multiplicador_Razonamiento': r['multiplicador_razonamiento'] or 'N/A'
                        })

                return cleaned_rows
    except Exception as exc:
        print(f"Database error loading {table_name}: {exc}")
        return _csv_fallback_rows(table_name)
