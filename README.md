# Semáforo IA - Especificación Técnica Detallada y Hoja de Ruta

## Acceso de demostracion

Las credenciales se almacenan como hashes PBKDF2 en `config.json`. Para el usuario
`nacha`, la clave vigente es `SemaforoIA1@`; para `maxine`, es `SemaforoIA2@`.
La clave antigua `654321` ya no es valida porque no cumple la politica minima de seguridad.

Este documento es la especificación técnica maestra (Technical Design Document) para el desarrollo del sistema Semáforo IA. Contiene el desglose a nivel de código, base de datos y algoritmos de los 70 Requerimientos Funcionales (RF) y 57 Casos de Uso estipulados en la documentación oficial.

Si vas a desarrollar en Python, debes seguir esta estructura paso a paso.

## Evidencias de presentación

### Ubicación de capturas RF10.2 a RF39.2

- **Figura 4.21, RF10.2:** abra **Impacto Ambiental** y capture la tarjeta **Tiempo de procesamiento** tras una ejecución menor a un segundo; mostrará `ms`. Evidencia técnica: `test_fast_execution_uses_millisecond_floor` y `test_metric_units_scale_with_values`.
- **Figura 4.24, RF12.1:** abra **Comparativas**. El bloque **Huella de Carbono Moderada** carga tres acciones desde `data/recommendation_rules.json`. Para el fallback, use `test_recommendation_manual_has_corruption_fallback`.
- **Figura 4.38, RF18.1:** abra **Modelos**, seleccione uno y use **Descripción Markdown del modelo → Guardar descripción**. Capture el contador; al superar `5000` el botón queda deshabilitado. Prueba: `test_markdown_editor_blocks_overflow_and_renders_saved_text`.
- **Figura 4.39, RF18.2:** en la misma vista, escriba `# Título`, `- **GPU**` y guarde. Capture el visor enriquecido sobre el editor. HTML peligroso se presenta como texto, no se ejecuta.
- **Figura 4.44, RF21.1:** abra **Cloud** y seleccione proveedor/región. Capture **Factor regional activo: ... gCO2eq/kWh**. Si la región no tiene factor, aparece **Factor regional no disponible; cálculo ambiental bloqueado**. Prueba: `test_cloud_view_blocks_when_regional_factor_is_missing`.
- **Figura 4.53, RF25.2:** abra **Hardware → Desglose de componentes**, asigne CPU/GPU y desmarque un componente. Capture el reparto recalculado a 100%. Al desmarcar el último, se restauran todos. Nota: el texto entregado rotula esta figura como “Caso 26.1”; debe corregirse a **Caso 25.2**.
- **Figura 4.61, RF29.2:** abra **Historial → Auditorías ambientales**. Capture la curva con dos o más registros. Con cero o uno, la gráfica muestra **Datos históricos insuficientes para trazar una evolución** y conserva la lista textual. Prueba: `test_sparse_history_uses_textual_fallback`.
- **Figura 4.64, RF31.2:** abra **Comparativas → Ineficiencias de software**, use duración `130000` ms y CPU `35`, pulse **Analizar eficiencia** y después **Abrir manual local**. Capture `CPU subutilizada` y su instrucción. Pruebas: `test_efficiency_finding_opens_local_manual` y `test_recommendation_manual_has_corruption_fallback`.
- **Figura 4.65, RF32.1:** abra **Comparativas → Carbon-aware shifting**, ingrese 24 factores separados por comas y pulse **Buscar mejor hora**. Capture hora UTC y ahorro. Con 24 valores iguales aparece **Matriz estable: no se recomienda postergar la ejecución**.
- **Figura 4.66, RF32.2:** en el mismo bloque capture las barras **Ahora** y **Recomendado**, junto al porcentaje de ahorro. Prueba: `test_carbon_shifting_shows_savings_and_hides_flat_comparison`.
- **Figura 4.67, RF33.1:** abra **Proyectos → Nuevo proyecto**, escriba un nombre y confirme. Capture el nuevo proyecto en el selector. Repetir el nombre muestra el rechazo de integridad.
- **Figura 4.68, RF33.2:** abra **Proyectos → Reasignar modelo**, elija modelo y proyecto destino y pulse **Transferir y recalcular**. El mismo proyecto y los destinos archivados no se ofrecen; los nombres de modelo duplicados en un proyecto se rechazan. Prueba: `test_model_name_is_unique_within_project`.
- **Figura 4.71, RF35.1:** configure **Administración → Sistema → Integraciones → URL factores CO2** y luego abra **Ajustes → Entorno y Hardware On-Premise → Sincronizar Factores Oficiales**. Capture la confirmación de sincronización o uso del respaldo local.
- **Figura 4.72, RF35.2:** tras al menos dos sincronizaciones, abra **Ajustes → Entorno y Hardware On-Premise → Restablecer a fecha pasada**, seleccione una instantánea fechada y capture **versión restaurada y métricas recalculadas**. Prueba: `test_carbon_factor_versions_can_be_restored`.
- **Figura 4.74, RF36.2:** abra **Ajustes → Entorno y Hardware On-Premise**, seleccione `SNMP` o `Modbus TCP`, complete host y OID/registro; para SNMP complete **Community SNMP**. Pulse **Probar Enlace Sensor On-Premise** y capture **Sondeo Activo** o el rechazo de autenticación. Prueba: `test_snmp_telemetry_passes_protected_community`.
- **Figura 4.80, RF39.1:** en **Proyectos**, fije una **Cuota USD** inferior al próximo costo y ejecute el modelo. Capture **Error guiado / ERR_QUOTA_FIN** y en **Costos FinOps** el estado **Disyuntor activo**. Si el diálogo falla, el núcleo mantiene el bloqueo, emite aviso del sistema y audita `circuit_notification_failed`.
- **Figura 4.81, RF39.2:** desde ese bloqueo complete **Override Administrativo** con cuenta admin, contraseña, motivo y vigencia. Capture la ejecución autorizada; credenciales inválidas mantienen el bloqueo. Pruebas: `test_governance_circuit_override_and_capacity_plan` y `test_admin_override_expiration_and_closed_project_block_execution`.

Para una captura consolidada de pruebas ejecute:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m unittest -v
```

### RF01.1 - Informe de costos y divisas

1. Abra **FinOps** con un proyecto activo que tenga ejecuciones.
2. Seleccione `USD`, `EUR` u otra moneda en el selector superior.
3. Capture las tarjetas de costo y el panel **Gasto por componente**; GPU, almacenamiento, red y servicios administrados se recalculan en la moneda elegida.
4. Pulse **Exportar** y capture el menú con `PDF`, `CSV` y `JSON`. Genere cada formato; todos incluyen totales, moneda y desglose por componente.
5. Para el caso sin tasa, retire temporalmente una tasa de `exchange_rates.json`, seleccione esa moneda y capture **Tasa no disponible... Seleccione otra moneda o actualice las tasas**. La exportación queda bloqueada hasta corregir la selección.

### RF01.2 - Datos FinOps y permisos de escritura

Use **FinOps → Exportar → CSV** o **JSON**. Para la captura positiva, abra el archivo y muestre las filas `component` con importe y unidad monetaria. Para el caso de permisos, seleccione como destino una carpeta protegida de Windows. El diálogo informa que no pudo escribir el informe y ofrece **Reintentar**; púlselo, elija **Documentos** y capture después la confirmación de guardado. El archivo fallido no se presenta como exportación exitosa.

### RF02.1 - Informe ambiental e integridad

1. Abra **Impacto Ambiental** con un proyecto activo.
2. Capture emisiones de entrenamiento/ejecución, energía, tiempo, agua, estado hídrico y contingencia.
3. Pulse **Exportar** y capture el menú con `PDF`, `CSV` y `JSON`; genere el formato exigido.
4. La exportación valida que las métricas sean numéricas, finitas y no negativas. El caso corrupto se acredita con `test_environmental_export_rejects_corrupt_metric`: muestra `ERR_DATA`, detiene el flujo y no invoca el generador.

### RF02.2 - Histórico de auditorías ambientales

Abra **Historial → Auditorías ambientales**. Capture **Auditorías recientes**: cada fila muestra fecha local, proyecto/modelo, estado del semáforo, carbono y costo, ordenada desde la más reciente. Para el estado sin datos, use una base nueva y capture **No hay auditorías ambientales registradas**.

### RF42.1 y RF42.2 - Capacity Planning histórico

Abra **Proyectos → Pronóstico pre-vuelo**, seleccione un modelo y pulse **Calcular pronóstico**. Con tres o más ejecuciones se muestran duración estimada, número de sesiones y dispersión. Un modelo nuevo muestra **Cálculo por determinarse**. **Invalidar pronóstico** devuelve al estado neutral; durante una simulación activa la invalidación se rechaza y conserva el valor vigente.

### RF43.1 y RF43.2 - Upgrade de hardware

Abra **Hardware**, seleccione un componente y pulse la acción de optimización. La recomendación sólo aparece cuando existe una alternativa con ahorro superior al 10% y retorno justificable. Al aplicar, el resumen de selección cambia inmediatamente. Si la metadata del candidato contiene `license_status: restricted` o `license_allowed: false`, se muestra **Actualización de hardware restringida** y se conserva el componente anterior.

### RF44.1 y RF44.2 - Cuotas por usuario

1. En **Administración → Sistema → Parámetros globales**, configure **Techo maestro USD** y **Techo maestro gCO2eq**.
2. En **Administración → Usuarios → Cuotas por usuario**, seleccione la cuenta subordinada y asigne sus cuotas.
3. Capture la asignación válida y luego un intento negativo o superior al techo maestro, que será rechazado.

### RF45.1 - Recuperación guiada y fallo fatal

Los errores recuperables de E/S abren **Error guiado** con código, causa, acción, detalle y copia/exportación de diagnóstico. El manejador global delega `MemoryError`, `SystemExit` y `KeyboardInterrupt` al hook nativo sin intentar reconstruir la UI. La primera rama es evidencia visual; la delegación fatal se acredita mediante la prueba automatizada correspondiente.

### RF45.2 - Portapapeles y archivo de diagnóstico

Para la **Figura 4.93**, abra **Administración → Auditoría → Verificar canal de diagnóstico**. En el diálogo **Error guiado**:

1. Pulse **Copiar detalles** y capture la confirmación **Diagnóstico completo copiado al portapapeles**.
2. Pulse **Exportar diagnóstico .txt** y capture la ruta mostrada bajo los botones.
3. El archivo queda en `error_reports/` e incluye identificador de incidente, fecha UTC, plataforma, versión de Python, PID, código, causa, acción y traza técnica completa.

Si el clipboard deniega la operación, **Copiar detalles** ejecuta automáticamente el mismo fallback `.txt` y muestra la ruta. Las pruebas automatizadas verifican textos superiores a 50 KB sin truncamiento y equivalencia exacta entre el contenido copiado y el archivo.

### RF61.2 - Reasignación y consolidados

1. Abra **Proyectos** y seleccione el proyecto de origen.
2. En **Reasignar modelo**, elija el modelo y el proyecto destino.
3. Pulse **Transferir y recalcular**.
4. Capture el mensaje verde persistente: muestra costos y carbono de origen y destino antes y después. Las tarjetas superiores quedan recalculadas.

La operación es transaccional. Si SQLite interrumpe el guardado, ambos proyectos quedan con `recalculation_pending=1` y la vista informa **Recálculo pendiente**.

### RF48.2 - Factor de emisión experimental

1. Abra **Ajustes → Entorno y Hardware On-Premise**.
2. Localice **Catálogo de factores de emisión**.
3. Escriba una fuente, por ejemplo `Gas Sintético`, y su valor en `gCO2eq/kWh`.
4. Pulse **Agregar factor**, seleccione la nueva fila y pulse **Aplicar factor seleccionado**.
5. Capture la fila marcada **Experimental local** y el mensaje verde **Factor activo**. La siguiente evaluación local utilizará este valor; Cloud conserva prioridad cuando está activo.

Los nombres vacíos, factores no numéricos, valores menores o iguales a cero y nombres duplicados son rechazados.

### RF62.2 - Centro de alertas presupuestarias

1. En **Proyectos**, configure **Cuota USD** y/o **Cuota gCO2eq**.
2. Registre ejecuciones que hagan pasar el consumo acumulado por 50% y 75%.
3. Abra **Administración → Auditoría → Alertas**.
4. Capture la tabla **Centro de alertas presupuestarias**, que muestra severidad, fecha, proyecto, umbral y detalle.

Los cruces de 50% son `PREVENTIVA`; los de 75% son `ALTA`. Un fallo exclusivo del buzón no cancela el cálculo principal.

### RF66.2 - Exportación autónoma y CLI

Desde la interfaz, abra **Proyectos → Exportar → Automatización CLI / CSV puro**. El diálogo muestra el comando PowerShell exacto, permite copiarlo y genera un CSV puro mediante **Exportar CSV puro ahora**.

En desarrollo:

```powershell
.\.venv\Scripts\python.exe cli.py --database semaforo.sqlite3 export --project-id 1 --output evidencia-rf66.csv
```

Después de ejecutar `build_exe.bat`, la distribución incluye un ejecutable de consola independiente:

```powershell
.\dist\SemaforoIA\SemaforoCLI.exe --database semaforo.sqlite3 export --project-id 1 --output evidencia-rf66.csv
```

`SemaforoCLI.exe` no inicia PySide6, devuelve códigos de salida al shell y rechaza IDs inexistentes con `Not found`. Debe distribuirse junto con `SemaforoIA.exe`.

## 1. Estructura de la Base de Datos (Diccionario de Datos)

El sistema requiere una persistencia relacional local (SQLite es ideal) estricta. Estas son las tablas y campos obligatorios que debes programar:

**Tabla Usuarios (Seguridad - RF55, RF56)**
* `id_usuario`: (PK) UUID o Integer.
* `email`: (Unique) Correo del usuario.
* `password_hash`: String encriptado (Bcrypt/Argon2).
* `rol`: Enum ( `admin`, `standard` ).
* `intentos_fallidos`: Integer (Default 0). Al llegar a 5, se bloquea (RF55.2).
* `is_locked`: Boolean.
* `force_password_change`: Boolean (RF59.2 - Para reset por admin).
* `presupuesto_max_dinero`: Float (RF44.1 - Cuota límite).
* `presupuesto_max_co2`: Float (RF44.2 - Cuota ecológica).

**Tabla Proyectos (Jerarquía - RF33, RF57, RF60)**
* `id_proyecto`: (PK).
* `nombre_proyecto`: String.
* `estado`: Enum ( `activo`, `archivado`, `cerrado` ). Si está archivado, es de solo lectura (RF60.2).
* `is_active`: Boolean (RF14.1 - Soft Delete).

**Tabla Modelos (Hijos de Proyectos - RF08, RF18, RF61)**
* `id_modelo`: (PK).
* `fk_proyecto`: (FK) Llave foránea hacia `Proyectos`.
* `nombre_modelo`: String.
* `descripcion_markdown`: Text (RF18.1 - Soporte Markdown).
* `modalidad`: Enum ( `Cloud`, `On-Premise` ) (RF16, RF17).

**Tabla Hardware_Catalog / Templates (RF26, RF27, RF40)**
* `id_hardware`: (PK).
* `nombre`: String.
* `tipo`: Enum ( `CPU`, `GPU`, `RAM`, `ASIC`, `Template` ).
* `tdp_watts`: Float (Consumo térmico base).
* `costo_hora`: Float (Precio base).
* `is_custom`: Boolean (Si fue creado por el usuario RF27).
* `soporta_inmersion`: Boolean (RF52.1 - Para refrigeración líquida).

**Tabla Historial_Ejecuciones (Time-Series - RF29, RF67)**
Nota: Todas las fechas deben guardarse estrictamente en ISO 8601 `YYYY-MM-DD HH:MM:SS`.
* `id_ejecucion`: (PK).
* `fk_modelo`: (FK).
* `timestamp_inicio`: DateTime.
* `timestamp_fin`: DateTime.
* `duracion_ms`: Integer (RF10.2 - Guardar en milisegundos si es < 1s).
* `kwh_total`, `co2_total`, `agua_total`, `costo_total`, `green_score`: Floats.
* `estado_semaforo`: Enum ( `Verde`, `Amarillo`, `Rojo` ).

## 2. Algoritmos y Motor Matemático Detallado

Debes programar estas funciones en tu backend Python exactamente con estas lógicas:

**A. Ecuación de Costo (TCO) y Divisas (RF01, RF06)**
```python
# Fórmula base
Costo_Base = (costo_hardware_por_hora * horas_ejecucion)
# RF06: Conversión de divisas
# Debes tener un diccionario de tasas: {'USD': 1.0, 'CLP': 950.0, 'EUR': 0.9}
Costo_Final = Costo_Base * tasa_conversion[divisa_seleccionada]
```

**B. Ecuación de Carbono Compleja (RF21, RF47, RF48, RF50)**
El cálculo de emisiones no es lineal, depende de condicionantes físicos:
```python
# 1. Calcular Energía (kWh)
# PUE (Power Usage Effectiveness): 1.0 es perfecto. Promedio 1.5. (RF47)
kWh = (tdp_total_watts * horas_ejecucion * PUE) / 1000

# 2. Determinar Factor de Emisión (CIF - gCO2eq/kWh)
# Si es Cloud (RF49): Usar CIF oficial de la región (Ej: AWS us-west-2).
# Si es On-Premise: Usar CIF personalizado del usuario (RF47.2).

# 3. Penalización Diésel (RF50.2 - Prorrateo híbrido)
# Si hubo un corte de luz y se usó generador Diésel:
horas_diesel = input_usuario
horas_red_normal = horas_ejecucion - horas_diesel
Emision = ( (horas_red_normal * CIF_Red) + (horas_diesel * CIF_Diesel_Castigo) )

# RF07.2: Escalar unidad
if Emision > 10000: return f"{Emision / 1000} kgCO2eq"
else: return f"{Emision} gCO2eq"
```

**C. Ecuación de Huella Hídrica Avanzada (RF51, RF52, RF53)**
```python
# WUE (Water Usage Effectiveness) = Litros evaporados por kWh
# WSI (Water Scarcity Index) = Multiplicador ético de sequía (1.0 normal, 3.0 Extremo)
if flag_inmersion_liquida == True: # RF52.1
    Litros_Agua = 0.0 # Se suprime el gasto evaporativo
else:
    Litros_Agua = kWh * WUE * WSI_Region
```

**D. Green Score (RF46)**
Debe ser un número del 1 al 100.
1. Calcular `% Presupuesto_Financiero_Usado`: `(Costo_Total / Límite_Costo) * 100`
2. Calcular `% Límite_Ecologico_Usado`: `(CO2_Total / Límite_CO2) * 100`
3. `Green_Score`: `100 - Promedio(%, %)`
4. Si `Score > 85 = "A+"`, `> 70 = "B"`, `< 50 = "C"` (RF46.2 Visual).

## 3. Algoritmos Heurísticos (Los "Consultores Inteligentes")

Estas son las funciones de Python más complejas que debes construir corriendo en segundo plano:

1. **Rightsizing (Mejora de Hardware - RF30)**
   * **Lógica:** Cada vez que el usuario elige un `CPU X`, lanza una consulta a la BD `SELECT * FROM Hardware_Catalog WHERE tipo = 'CPU'`. Itera sobre los resultados. Si `Nuevo_CPU_TDP < CPU_Actual_TDP` y la diferencia de consumo genera un ahorro `> 10%`, dispara una sugerencia en la interfaz (RF30.1).
   * **Acción (RF43.2):** Botón "Aplicar". Reemplaza el `id_hardware` en memoria y recalcula todo.

2. **Carbon-Aware Shifting (Desplazamiento Temporal - RF32)**
   * **Lógica:** Debes tener un array de 24 horas simulando el CIF de la red eléctrica. (Ej: `[400g, 380g, ..., 150g(3AM), ...]`). El script busca el índice del array con el valor mínimo (`min(cif_array)`). Si la hora actual está en un pico (ej. 14:00 hrs) y el valle es a las 03:00 AM, imprime: *"Retrase tarea hasta las 03:00 para ahorrar X% de CO2"*.

3. **Extrapolación de Quiebre de Cuota (RF38, RF22.2)**
   * **Lógica:** Si hoy es el día 15 del mes y el usuario ha gastado $500 (de un límite de $800).
   * `Velocidad_gasto_diario = 500 / 15 = $33.3/dia`.
   * `Proyeccion_fin_de_mes = 33.3 * 30 = $1000`.
   * Si `1000 > 800`: Disparar alerta roja inmediata e inyectar log en el historial de eventos (RF62.2).

## 4. Lógicas Estrictas de Interfaz de Usuario (UI/UX)

Si usas Streamlit o React (o PySide6 en este caso), debes programar estos comportamientos exactos:

1. **Evaluación Semafórica Obligatoria (RF70, RF03-05):**
   * La UI debe tener inputs para configurar los umbrales (Ej: 50% y 90%).
   * RF70.1 (Anti-Colisión): Debes programar una validación cruzada. Si el usuario intenta poner Verde en 60% y Amarillo en 55%, lanza un error y bloquea el guardado. `Verde MUST be < Amarillo MUST be < Rojo`.

2. **Snooze (Silenciador - RF38.2, RF69.2):**
   * Todas las alertas heurísticas deben tener un botón "X" o "Silenciar".
   * En Python, guarda un flag en la sesión (`session_state['snooze_alert_X'] = True`) para que el renderizador de la alerta retorne nulo y la alerta desaparezca, devolviendo la fluidez a la pantalla.

3. **Tooltip de Riesgo (RF04.2):**
   * Si el semáforo está amarillo, al pasar el mouse por encima (`onHover`), el sistema debe inspeccionar el objeto JSON del cálculo, buscar la variable con mayor porcentaje de uso (ej. `consumo_gpu`) y mostrar en el tooltip: *"La GPU está generando el 80% del impacto"*.

4. **Desglose Visual (RF25, RF68):**
   * Gráfico de Torta (Pie Chart) dinámico dividiendo CPU vs GPU vs RAM.
   * Si el usuario desmarca la CPU, el gráfico debe recalcular el 100% solo con GPU y RAM (RF25.2).
   * Mostrar un texto estático imperativo (RF68): *"Fuente Primaria Operante: [Tipo de Energía]"*.

5. **Doble Barra de Progreso (RF62, RF63):**
   * Renderizar dos barras de estado paralelas en la cabecera del proyecto:
   * Una para `% de Dinero Gastado` y otra para `% de Límite de Carbono Gastado`.

## 🔌5. Integraciones Externas, APIs y Telemetría

Estos son los scripts de conexión externa que debes desarrollar (Módulos 5 y 11):

1. **API Rest de Billing Cloud (RF34):**
   * Crear una función asíncrona (ej. usando la librería `requests` de Python) que consulte una URL de precios (puedes simular un endpoint con un JSON estático si no tienes llaves de AWS reales).
   * RF34.2 (Seguridad): El input donde el usuario ingresa su API Key debe ser de tipo password (ofuscado) y guardarse en base de datos encriptado.

2. **API Meteorológica / CIF (RF35):**
   * Función que descargue un diccionario JSON actualizado con los factores de carbono por país. Debe tener manejo de Timeout (RF35.1_Exc1): Si la API se cae o no hay internet, el sistema debe usar un bloque `try/except` y hacer fallback cargando el último JSON guardado en el disco duro.

3. **Telemetría On-Premise LAN (RF36):**
   * En un escenario real, esto se hace con la librería `pysnmp` o `pymodbus` enviando pings a la IP de una regleta inteligente (PDU).
   * Para tu desarrollo, crea un script "Simulador de Regleta" que genere un número aleatorio entre 100W y 500W cuando el usuario apriete el botón "Probar Enlace Sensor" (RF36.2). Si la IP no existe, lanza el error "Timeout de conexión" (RF36.1_Exc2).

4. **Notificaciones al Sistema Operativo (RF37):**
   * Al terminar un cálculo masivo (ej. un bucle de simulación pesado), usar la librería `plyer` (o `win10toast` en Windows) para lanzar un pop-up nativo del sistema operativo: *"Semáforo IA: Evaluación completada"*. Debe existir un toggle en Ajustes para apagar esto (Modo Concentración - RF37.2).

---

## 🛠️6. Checklist de Implementación Estricto (Tareas Faltantes)

Aquí se enumeran las tareas pendientes (lo que falta hacer) en la base de código actual:

### Base de Datos y Modelos
- [ ] Tabla Usuarios con validación Regex estricta de contraseña (`@`, `-`, `_`, mayúscula, número, min 8 chars) (RF56.1).
- [ ] Sistema de Autenticación (Login) con bloqueo tras 5 intentos fallidos (RF55.2).
- [ ] Tablas relacionales: `Proyecto -> Modelo -> Hardware`.
- [ ] Implementar borrado lógico (`is_active = False`) para mantener históricos (RF14.1).
- [ ] Función para reasignar un modelo de un Proyecto A a un Proyecto B, recalculando inmediatamente los totales de ambos proyectos (RF61.1, RF61.2).

### Motor Matemático
- [ ] Integrar variable WSI (Estrés hídrico) a la ecuación de agua (RF53).
- [ ] Lógica para refrigeración líquida: Si `inmersion == True`, multiplicar consumo de agua por 0 (RF52.1).
- [ ] Cálculo de penalización prorrateada: Mezclar horas Diésel vs horas de Red Normal en el mismo cálculo (RF50.2).
- [ ] Función Green Score (1-100) con asignación de letras (A, B, C) (RF46.1).

### Front-End y Visualización
- [ ] Validar que los inputs de Semáforo (Verde, Amarillo, Rojo) no se crucen numéricamente (RF70.1).
- [ ] Doble barra de progreso en cabecera: TCO (Dinero) vs Límite Ecológico (RF62, RF63).
- [ ] Vista comparativa (Lado a Lado): Permitir seleccionar 2 modelos y pintar de color verde las celdas del modelo ganador (RF24.1, RF24.2).
- [ ] Gráfico porcentual CPU vs RAM vs GPU recalculable si se apaga un componente (RF25).
- [ ] Botones "Snooze" en las alertas de recomendaciones para minimizarlas a la sesión actual (RF69.2).

### APIs y Telemetría
- [ ] Integrar input seguro (oculto) para las API Keys de los proveedores cloud (RF34.2).
- [ ] Simulador de botón Probar Enlace Sensor LAN con respuestas OK o Timeout (RF36.2).
- [ ] Botón de descarga de "Nuevos factores ambientales" (API Mock) con fallback a archivo local si falla el internet (RF35.1).

### Inteligencia y Exportación
- [ ] Algoritmo de "Rightsizing": Que el sistema busque en SQLite si hay un CPU mejor y lance alerta (RF30.1).
- [ ] Algoritmo de Extrapolación: Que el sistema divida el consumo actual por los días transcurridos y alerte si se va a romper la cuota a fin de mes (RF38.1).
- [ ] Exportación a JSON y CSV de datos matemáticos puros (RF66).
- [ ] Exportación de Reporte Ejecutivo PDF (Usando `reportlab` o similar) (RF28.1).

---

##  Pipeline de Finalización del Código (Hoja de Ruta de Implementación)

## Crear ejecutable para Windows

Para crear una versión que pueda ejecutarse en un PC sin Python instalado, abre
`build_exe.bat` desde este directorio. El script crea o reutiliza `.venv`, instala
las dependencias y PyInstaller, y genera una distribución en:

`dist\SemaforoIA\SemaforoIA.exe`

El script verifica que cree la subcarpeta `_internal` y que incluya la DLL de
Python antes de terminar. Hay que copiar la carpeta completa `dist\SemaforoIA`, no solamente el `.exe`,
porque contiene las librerías y recursos de la aplicación. `config.json` queda
junto al ejecutable para que la configuración pueda modificarse en el PC destino.

Si aparece `Failed to load Python DLL`, elimina la copia anterior y vuelve a
copiar la carpeta completa manteniendo la subcarpeta `_internal`. El ejecutable
debe iniciarse desde `dist\SemaforoIA\SemaforoIA.exe`; no debe separarse de esa
carpeta. Si el error continúa, instala en el PC destino el paquete oficial
`Microsoft Visual C++ Redistributable 2015-2022` de 64 bits y verifica que el
antivirus no haya puesto archivos de `_internal` en cuarentena.

Cómo se planea continuar haciendo el código y terminar el proyecto:

### Fase 1: Arquitectura y Base de Datos (Persistencia Fuerte)
1. Sustituir los mocks de datos por una conexión a base de datos SQLite.
2. Crear las tablas relacionales especificadas (Usuarios, Proyectos, Modelos, Hardware, Historial_Ejecuciones).
3. Implementar el motor de autenticación en Python que maneje bloqueos por intentos fallidos, hasheo de contraseñas y validación por regex estricta.
4. Desarrollar un borrado lógico (soft-delete) global.

### Fase 2: Construcción del Motor Matemático Completo
1. Programar la ecuación de TCO (Costo Total de Propiedad) integrando la conversión de divisas.
2. Programar la Ecuación de Carbono Compleja (integrando PUE, CIF, y penalización híbrida diésel/red).
3. Programar la Ecuación de Huella Hídrica Avanzada (WSI, WUE y la condición de inmersión líquida).
4. Unificar todo en la función maestra de Green Score (0 a 100) y asignarle letras (A, B, C).

### Fase 3: Algoritmos Heurísticos en Segundo Plano
1. Implementar la función de *Rightsizing*, comparando consumos de hardware en SQLite y despachando alertas si el ahorro es > 10%.
2. Desarrollar el *Carbon-Aware Shifting*, identificando el valle mínimo en la curva horaria de CIF.
3. Construir el *Algoritmo de Extrapolación de Quiebre de Cuota* para proyectar el consumo diario frente al límite del mes, disparando alertas proactivas.

### Fase 4: Refinamiento de la Interfaz (PySide6)
1. Integrar validación anti-colisión en los componentes UI para los límites del Semáforo IA (Verde < Amarillo < Rojo).
2. Construir la Doble barra de progreso en la ventana principal, vinculando visualmente al TCO y Límite Ecológico calculados en la BD.
3. Desarrollar un Gráfico de Torta interactivo (CPU/RAM/GPU) que recalcule porcentajes en tiempo real si el usuario simula apagar componentes.
4. Armar el diseño Side-by-Side para comparativas directas entre 2 modelos IA distintos.
5. Perfeccionar las Tooltips interactivas de riesgos y el botón *Snooze* de alertas temporales usando estados en memoria.

### Fase 5: Módulos de Integración, Exportación y Telemetría
1. Escribir conectores mockeados para Billing Cloud y API Meteorológica (simulando peticiones HTTP que usen archivos locales de respaldo ante "caídas" de internet).
2. Crear el "Simulador LAN PDU" que genere pings y latencias pseudo-aleatorias hacia un sensor de energía de hardware local.
3. Programar exportación pura a JSON/CSV.
4. Implementar ReportLab para autogenerar informes ejecutivos ESG en formato PDF y disparar notificaciones emergentes en el SO a la culminación de procesos pesados.
