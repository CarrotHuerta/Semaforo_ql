import psycopg2
import psycopg2.extras
import os

DB_CONFIG = {
    "dbname": os.environ.get("DB_NAME", "greenops"),
    "user": os.environ.get("DB_USER", "jules"),
    "password": os.environ.get("DB_PASSWORD", "password"),
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432")
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def load_db_rows(table_name):
    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                # The user's application logic previously relied entirely on CSVs.
                # To minimize breakages for the presentation while genuinely
                # adopting the SQL database schema provided, we will map the
                # actual schema tables back to the exact format expected by the frontend.

                cleaned_rows = []

                if table_name == "hardware_csv":
                    # Maps to componente_hardware
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
    except Exception as e:
        print(f"Database error loading {table_name}: {e}")
        return []
