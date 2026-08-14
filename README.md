# 🚦Semáforo IA - Especificación Técnica Detallada y Hoja de Ruta

Este documento es la especificación técnica maestra (Technical Design Document) para el desarrollo del sistema Semáforo IA. Contiene el desglose a nivel de código, base de datos y algoritmos de los 70 Requerimientos Funcionales (RF) y 57 Casos de Uso estipulados en la documentación oficial.

Si vas a desarrollar en Python, debes seguir esta estructura paso a paso.

## 🗄️1. Estructura de la Base de Datos (Diccionario de Datos)

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

## 🧮2. Algoritmos y Motor Matemático Detallado

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

## 🧠3. Algoritmos Heurísticos (Los "Consultores Inteligentes")

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

## 🖥️4. Lógicas Estrictas de Interfaz de Usuario (UI/UX)

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

## 🚀 Pipeline de Finalización del Código (Hoja de Ruta de Implementación)

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
