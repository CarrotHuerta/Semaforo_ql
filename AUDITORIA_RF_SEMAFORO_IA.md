# Auditoria funcional y tecnica de Semaforo IA

**Fecha:** 2026-08-24  
**Alcance:** RF01-RF70 y sus casos de uso y excepciones.  
**Criterio:** Un requisito solo se considera listo cuando estan implementados sus casos de uso, persistencia, validaciones y excepciones. Un campo SQL o un boton que solo muestra un mensaje no cuenta como implementacion.

## Actualizacion posterior a correcciones

Se implementaron y verificaron con pruebas automatizadas las siguientes piezas funcionales:

- Motor independiente para costo, divisas, energia, carbono, diesel, agua, WUE, WSI, inmersion, Green Score y semaforo.
- Validacion de umbrales con la regla `Verde < Amarillo < Rojo`.
- Hash PBKDF2 de contrasenas, validacion de complejidad y bloqueo persistente despues de cinco fallos.
- Migracion de las credenciales de demostracion en `config.json` a `password_hash`.
- Persistencia SQLite local para usuarios, proyectos, modelos y ejecuciones.
- Importacion y exportacion validada de JSON/CSV, incluyendo deteccion de archivos corruptos.
- Soft-delete y hard-delete sobre el archivo local de modelos.
- Backup real de la base local desde Ajustes.
- Prueba de sensor simulada con lectura entre 100 W y 500 W y timeout controlado.
- Guardado y restablecimiento de umbrales desde Ajustes.
- Login local probado con `load_config()` real y credenciales hash; el semaforo usa ahora `calculate_carbon()` en lugar de la formula aproximada anterior.
- CRUD local de proyectos y modelos, archivado solo lectura, reasignacion transaccional, totales por proyecto e historial.
- Estimacion cloud con trazabilidad de entradas y calculo integral de una ejecucion persistible.
- Comparativa limitada de modelos con deteccion de empate tecnico.
- Validacion de longitud y saneamiento de HTML para descripciones Markdown.
- Historial de ejecuciones conectado a SQLite y estado explicito cuando no existen registros.
- Heuristicas de rightsizing y pronostico de quiebre presupuestario cubiertas con pruebas.
- Vista Comparativas con seleccion de dos modelos, emisiones lado a lado y empate tecnico.
- Catalogo de Hardware con sugerencia visible de alternativa que ahorra mas del 10%.
- Comparativa, rightsizing, historial, sensor y estados vacios con textos disponibles en espanol e ingles.
- Panel administrativo para consultar intentos y bloqueos, con desbloqueo restringido al rol Administrador.
- Login distingue `Usuario bloqueado` de contraseña incorrecta y traduce el mensaje a `User locked`.
- Doce pruebas automatizadas en `test_functional_core.py`, todas exitosas.

Estas correcciones no permiten marcar un bloque completo como `[LISTO]` porque los bloques restantes aun incluyen funcionalidades no implementadas, como APIs externas, SNMP/Modbus real, XLSX, Markdown renderizado, aplicacion persistente del hardware recomendado, capacity planning, notificaciones OS, cuotas y disyuntores. El estado se mantiene estricto hasta completar tambien esas excepciones.

### Estado verificado de componentes

Estos componentes se consideran `[LISTO]` porque tienen implementacion en el codigo y cobertura en `test_functional_core.py`:

- `[LISTO]` Motor de costo, divisas, energia, carbono con diesel, agua con WUE/WSI/inmersion, Green Score y semaforo.
- `[LISTO]` Validacion anti-colision de umbrales (`Verde < Amarillo < Rojo`).
- `[LISTO]` Autenticacion PBKDF2, politica de contrasenas, bloqueo persistente tras cinco fallos y desbloqueo por Administrador.
- `[LISTO]` Persistencia SQLite de usuarios, proyectos, modelos y ejecuciones, incluyendo historial vacio explicito.
- `[LISTO]` Reasignacion transaccional de modelos y totales por proyecto.
- `[LISTO]` Importacion y exportacion de JSON/CSV con deteccion de corrupcion.
- `[LISTO]` Vista de modelos integrada con `models.json`; las importaciones se refrescan en el selector y excluyen registros inactivos.
- `[LISTO]` Borrado logico y fisico del archivo local de modelos.
- `[LISTO]` Backup SQLite consistente mediante la API online de SQLite; la interfaz de Ajustes usa este mecanismo.
- `[LISTO]` Sensor simulado con rango 100-500 W y timeout controlado.
- `[LISTO]` Comparativa de dos modelos con deteccion de empate tecnico.
- `[LISTO]` Rightsizing con umbral de ahorro superior al 10% y aplicacion sobre el hardware seleccionado.
- `[LISTO]` Pronostico de quiebre presupuestario y trazabilidad de estimaciones cloud.
- `[LISTO]` Saneamiento y limite de longitud para descripciones con contenido tipo Markdown.
- `[LISTO]` Semaforo inicial conectado a `calculate_carbon()`, `semaphore_level()` y umbrales persistidos.
- `[LISTO]` Green Score de la evaluacion inicial calculado por `green_score()`; el costo se considera cero cuando esta vista no tiene una tarifa seleccionada.
- `[LISTO]` Metricas locales PUE y porcentaje de energia verde validadas y persistidas en `config.json`.
- `[LISTO]` Exportacion del informe de Inicio alineada con el dashboard: impacto, Green Score, nivel y progreso usan los mismos valores calculados.
- `[LISTO]` Divisas FinOps conectadas por HTTP GET con `requests` a Open ER API usando CLP como base, con 10 monedas extranjeras, conversión desde CLP, tasa inversa y fallback local.
- `[LISTO]` Login del servidor alineado con SQLite/PBKDF2, bloqueo tras cinco fallos, roles y respuesta diferenciada para usuario bloqueado.
- `[LISTO]` API HTTP del servidor con validación de `Content-Type`, límite de cuerpo, JSON controlado, códigos HTTP consistentes y servidor concurrente.
- `[LISTO]` Acceso remoto unificado: login entrega token firmado con vencimiento y `/hardware` exige `Authorization: Bearer`.
- `[LISTO]` Registros HTTP sin cuerpos ni credenciales; las respuestas de error exponen solo mensajes controlados.
- `[LISTO]` Valores demostrativos de FinOps separados en `data/finops_demo.csv`; tarjetas, desglose y barra se calculan desde ese archivo.
- `[LISTO]` Actualización de divisas en segundo plano con botón de reintento, indicador de estado y cache local, sin bloquear la interfaz.
- `[LISTO]` Notificaciones OS opcionales mediante `plyer`, con preferencia persistida en `config.json` y respetada por las exportaciones completadas.
- `[LISTO]` Exportación XLSX integrada en `export_handler` y disponible para informes Inicio, Ambiental y FinOps, con hojas de KPIs, detalles, logs y resumen.

Componentes que siguen `[PARCIAL]` o `[PENDIENTE]`: calculos visuales demostrativos en algunas vistas, sincronizacion real de factores ambientales y tarifas cloud, persistencia cifrada de API keys, graficos CPU/RAM/GPU, cuotas y disyuntores, SNMP/Modbus, Markdown renderizado y capacity planning.

## 1. Resumen ejecutivo

**Resultado:** 0 de 30 bloques funcionales evaluados como completamente listos bajo el criterio estricto de este documento. Sin embargo, hay componentes individuales ya implementados y probados; se marcan como `[LISTO]` en el checklist actualizado.

El proyecto cuenta actualmente con:

- Interfaz de escritorio PySide6.
- Esquema relacional PostgreSQL en `basededatossql`.
- Carga de datos estaticos desde CSV.
- Generacion parcial de informes PDF y JSON.
- Sistema de traducciones en `i18n.py` y `locales/translations.json`.
- Algunos controles visuales para semaforo, progreso, importacion, backup, sincronizacion y alertas.

Las deficiencias que permanecen son principalmente:

- Integracion incompleta entre algunas vistas y la persistencia local.
- Botones de sincronizacion, tarifas, notificaciones y algunas metricas que aun solo muestran mensajes.
- Algunas vistas ambientales y cloud todavía contienen datos visuales demostrativos.
- Ausencia de APIs cloud, SNMP/Modbus, notificaciones OS y fallback de datos.
- Ausencia de capacity planning, cuotas/disyuntores y exportacion XLSX.
- Markdown sanitizado pero aun no renderizado en la interfaz.

## 2. Evidencia revisada

- `main.py`: UI, datos estaticos, semaforo, exportacion y controles de configuracion.
- `db.py`: conexion PostgreSQL y lecturas parciales; la operacion funcional actual usa `LocalStore` sobre SQLite.
- `server.py`: servidor HTTP local con login SQLite/PBKDF2, tokens firmados para `/hardware` y validaciones HTTP.
- `basededatossql`: esquema relacional amplio, pero sin capa de servicios que lo utilice completamente.
- `export_handler.py`: exportacion PDF/JSON con worker Qt.
- `export handler/eco.py`, `economia.py` e `inicio.py`: plantillas PDF y JSON.
- `data/hardware.csv`, `data/intensidad_carbono.csv` y `data/modelos_ia.csv`: fuentes estaticas.
- `requirements.txt`: no incluye librerias para SNMP, Modbus, notificaciones OS, criptografia, XLSX o Markdown.
- `config.json`: usuarios de demostracion con hashes PBKDF2; no se deben reintroducir claves en texto plano.

## 3. Evaluacion completa

### 3.1 Informes y exportacion

#### RF01 - Informe de costos

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar costo por componente, horas de ejecucion y costo total.
- Implementar conversion por divisa usando tasas persistidas y validar divisas no soportadas.
- Sustituir valores hardcodeados por datos de modelo y hardware.
- Manejar errores de lectura de datos y errores de permisos al escribir.
- Completar exportacion CSV y JSON de datos crudos.

#### RF02 - Informe medioambiental

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar calculo real de kWh y gCO2eq.
- Validar datos corruptos, nulos o incompatibles.
- Persistir informes y ejecuciones en `historial_ejecucion`.
- Crear vista de historial y mensaje controlado para historial vacio.
- Manejar errores del motor de calculo.

### 3.2 Visualizacion y alertas

#### RF03 - Semaforo verde menor a 50 por ciento

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Calcular el nivel a partir de metricas reales y umbrales configurables.
- Mostrar estado de datos insuficientes.
- Actualizar el indicador cuando cambie el consumo.
- Mostrar estado de carga durante calculos complejos.

#### RF04 - Semaforo amarillo entre 50 y 90 por ciento

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Conectar el estado amarillo al calculo real.
- Manejar errores de calculo sin dejar un estado incorrecto.
- Identificar la variable con mayor impacto.
- Mostrar el parametro responsable en el detalle o tooltip.

#### RF05 - Semaforo rojo mayor a 90 por ciento

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Conectar el estado rojo a los limites reales.
- Manejar fallos de procesamiento.
- Implementar cancelacion real del modelo o proceso.
- Evitar bloquear la UI al abortar un proceso OS.

#### RF06 - Formato economico

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Mostrar costos calculados con exactamente dos decimales y simbolo.
- Mostrar `0.00` para costos nulos.
- Usar tasas de conversion persistidas para USD, CLP y EUR.
- Informar claramente cuando no exista factor de conversion.

#### RF07 - Metricas ambientales visuales

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Mostrar kWh y gCO2eq provenientes del motor de calculo.
- Inicializar y validar todas las variables.
- Convertir automaticamente a kgCO2eq cuando el valor supere 10.000 g.
- Manejar errores de conversion y redondeo.

#### RF08 - Lista paginada

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar paginacion real de modelos.
- Mostrar estado vacio cuando no existan registros.
- Implementar ordenamiento por columnas.
- Manejar fallos de memoria y evitar ordenar listas sin limite.

#### RF09 - Componentes de hardware

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Listar TDP, vCPUs y RAM asociados al modelo.
- Validar propiedades tecnicas faltantes.
- Implementar desglose matematico por componente.
- Manejar variables base no cargadas antes de calcular.

#### RF10 - Tiempo de ejecucion

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar cronometro de inicio y fin.
- Mostrar duraciones normales en formato `HH:MM:SS`.
- Mostrar milisegundos para duraciones menores a un segundo.
- Persistir la duracion en `historial_ejecucion`.
- Manejar errores o limitaciones del reloj del sistema.

#### RF11 - Modal de advertencia

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar modal destacado para niveles amarillo y rojo.
- Permitir cierre controlado del modal.
- Evitar que una alerta critica desaparezca incorrectamente.
- Recalcular la visibilidad cuando cambie la persistencia de la alerta.

#### RF12 - Recomendaciones accionables

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar reglas para generar recomendaciones amarillas.
- Mostrar una correccion concreta y contextual.
- Hacer que el boton Aplicar modifique realmente la configuracion o hardware.
- Rechazar automaticamente parametros bloqueados manualmente.
- Manejar reglas que no sean aplicables.

### 3.3 Archivos y persistencia

#### RF13 - Importacion masiva

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Leer archivos JSON y CSV desde disco.
- Validar formato y esquema antes de insertar.
- Mostrar previsualizacion de registros.
- Impedir carga de estructuras incomprensibles.
- Informar errores por fila sin corromper la importacion completa.

#### RF14 - Eliminacion de modelos

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar soft-delete mediante estado o bandera persistida.
- Excluir modelos eliminados de calculos nuevos y conservar su historial.
- Implementar hard-delete con confirmacion y transaccion.
- Impedir eliminar modelos protegidos o con dependencias.
- Manejar archivos en uso.

#### RF15 - Persistencia de datos

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Completar CRUD de usuarios, proyectos, modelos, hardware y ejecuciones.
- Resolver la discrepancia entre la especificacion local SQLite y la implementacion PostgreSQL.
- Manejar permisos insuficientes en disco.
- Implementar backup local real.
- Impedir backup inconsistente durante un calculo critico.

### 3.4 Datos y origen

#### RF16 - Telemetria On-Premise

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar lectura de watts desde sensores reales.
- Integrar SNMP o Modbus TCP.
- Manejar sensor inaccesible y timeout.
- Implementar calibracion del factor de perdidas.
- Rechazar ajustes superiores al 50 por ciento.

#### RF17 - Estimacion Cloud

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Estimar consumo y costo por instancia cloud y promedios.
- Validar instancias desconocidas.
- Guardar las variables de entrada usadas en cada estimacion.
- Detectar datos de origen corruptos.

#### RF18 - Markdown

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Aplicar limite de caracteres al campo de descripcion.
- Renderizar Markdown en la interfaz.
- Sanitizar contenido para evitar inyeccion HTML o scripts.
- Mostrar error controlado para sintaxis invalida.

### 3.5 Configuracion global

#### RF19 - Configuracion de umbrales

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Validar que Verde sea menor que Amarillo y Amarillo menor que Rojo.
- Rechazar rangos negativos, mayores a 100 o solapados.
- Persistir cambios por usuario o proyecto.
- Implementar restauracion real desde valores de fabrica.
- Manejar archivo base inexistente.

#### RF20 - Region Cloud

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar selector de regiones.
- Manejar errores de lectura de la lista.
- Filtrar regiones renovables.
- Mostrar estado controlado cuando el filtro no devuelve resultados.

#### RF21 - Calculo de huella regional

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar `kWh = tdp * horas * PUE / 1000`.
- Multiplicar energia por el factor regional gCO2eq/kWh.
- Rechazar regiones sin diccionario local.
- Validar fecha de actualizacion y vigencia de 365 dias.
- Manejar timestamps corruptos.

#### RF22 - Tope presupuestario

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Permitir fijar un limite USD.
- Rechazar limites negativos o incoherentes.
- Calcular velocidad de gasto y fecha estimada de quiebre.
- Manejar historial insuficiente para el pronostico.

#### RF23 - Tope ecologico

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Permitir fijar limite de CO2.
- Validar cifras absurdas o negativas.
- Bloquear ejecuciones cuando se alcance el limite.
- Implementar excepcion mediante pase manual de Admin.
- Registrar cada desbloqueo.

### 3.6 Comparacion y hardware

#### RF24 - Comparativa concurrente

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Permitir seleccionar varios modelos y mostrarlos lado a lado.
- Aplicar limite maximo de modelos.
- Calcular metricas comparables.
- Resaltar el optimo en verde.
- Mostrar tratamiento especifico para empates tecnicos.

#### RF25 - Grafico porcentual

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar grafico dinamico CPU/RAM/GPU.
- Recalcular porcentajes cuando se oculte un componente.
- Mantener una categoria visible si se ocultan las demas.
- Mostrar datos en texto si falla la libreria grafica.

#### RF26 - Catalogo base

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Validar y cargar el catalogo offline.
- Manejar catalogo corrupto.
- Implementar filtro por TDP.
- Mostrar mensaje cuando ningun elemento coincida.

#### RF27 - Componentes personalizados

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Crear hardware custom desde la interfaz.
- Validar TDP, costo, cantidad y demas valores numericos.
- Permitir editar solo componentes custom.
- Bloquear modificaciones al catalogo de fabrica.

#### RF40/41 - Templates de hardware

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Crear plantillas y asociar componentes.
- Poblar plantillas con cantidades validas.
- Generar y recuperar IDs de forma segura.
- Detectar lecturas corruptas.
- Exportar e importar JSON con esquema y validacion.
- Manejar denegacion de escritura del sistema operativo.

### 3.7 Trazabilidad y reportes

#### RF28 - Reportes exportables

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Conectar el PDF ejecutivo a datos reales.
- Manejar fallo del motor PDF.
- Implementar exportacion XLSX.
- Manejar archivo abierto o bloqueado.
- Verificar integridad del archivo antes de informar exito.

#### RF29 - Bitacora Time-Series

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Registrar cada ejecucion como copia de solo lectura.
- Guardar timestamps y duraciones en formato requerido.
- Manejar errores fisicos de disco.
- Crear grafica evolutiva.
- Mostrar texto alternativo si faltan datos.

### 3.8 Consultoria e IA heuristica

#### RF30 - Rightsizing de hardware

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Buscar CPUs candidatas en el catalogo.
- Comparar TDP actual y alternativo.
- Emitir sugerencia solo si el ahorro supera el 10 por ciento.
- Mostrar estado cuando no existan alternativas mejores.
- Permitir silenciar temporalmente la alerta.
- Reactivar la alerta cuando cambien los datos relevantes.

#### RF31 - Ineficiencias de software

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar deteccion o reglas de ineficiencia logica.
- No sugerir cambios cuando el consumo sea normal.
- Abrir un manual local de buenas practicas.
- Manejar documento inexistente o corrupto.

#### RF32 - Carbon-aware shifting

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Mantener matriz CIF de 24 horas.
- Detectar la hora de menor intensidad.
- Sugerir cambio horario con ahorro estimado.
- Manejar matriz plana sin beneficio.
- Mostrar datos en texto si falla el grafico de barras.

#### RF42/43 - Capacity Planning y recambio

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar prediccion estadistica de costo y duracion.
- Manejar ausencia de historial.
- Permitir invalidacion manual sin depender de procesos bloqueados.
- Detectar hardware o tecnologia nueva.
- No recomendar recambio si el componente actual es optimo.
- Implementar actualizacion de catalogo y manejo de base corrupta.

### 3.9 Integracion externa API/LAN

#### RF33 - Entidad Proyectos

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Crear proyectos desde la interfaz y persistirlos.
- Asociar modelos respetando claves foraneas.
- Rechazar nombres duplicados.
- Validar incompatibilidades relacionales.

#### RF34 - APIs Billing Cloud

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar cliente de sincronizacion de tarifarios.
- Configurar timeout, errores de red y reintentos.
- Guardar API keys cifradas, nunca en texto plano.
- Usar campo de entrada tipo password.
- Validar la llave mediante ping y rechazar llaves invalidas.

#### RF35 - Fuentes CO2 oficiales

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Descargar y validar catalogo oficial.
- Manejar respuestas HTTP 404 y 500.
- Guardar ultima version valida localmente.
- Usar fallback cuando no exista red.
- Revertir al diccionario del ano anterior si esta disponible.
- Manejar fichero de respaldo perdido.

#### RF36 - Sensores LAN On-Premise

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Integrar SNMP o Modbus TCP.
- Implementar sondeo a PDU y lectura de watts.
- Implementar boton de prueba de enlace.
- Crear simulador de respuestas OK y Timeout.
- Manejar timeout LAN y autenticacion rechazada.

### 3.10 Disyuntores y seguridad

#### RF37 - Alertas OS

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Integrar `plyer` o `win10toast`.
- Emitir Toast al terminar calculos masivos.
- Implementar modo Concentracion.
- Manejar bloqueo de globos por el sistema operativo.

#### RF38/39 - Disyuntores

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar extrapolacion predictiva de CO2 y cuotas.
- Manejar extrapolacion imposible o datos insuficientes.
- Implementar corte financiero duro.
- Registrar el corte y el motivo.
- Implementar pase Admin con validacion de clave.
- Rechazar claves Admin incorrectas.

#### RF45/46 - Manejo de errores y Green Score

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Crear flujo guiado de recuperacion manual.
- Mostrar codigo, causa y accion recomendada.
- Permitir copiar logs al portapapeles.
- Manejar bloqueo del portapapeles.
- Calcular Green Score ponderando gasto y CO2.
- Mantener rango de 1 a 100.
- Asignar sello A+, B o C.
- Mostrar N/A cuando el calculo este incompleto.

### 3.11 Datacenter, agua y matrices

#### RF47/48 - Matrices privadas

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Permitir modificar PUE fisico.
- Permitir modificar porcentaje renovable PPA.
- Validar que la suma de componentes no supere 100 por ciento.
- Leer el diccionario energetico local.
- Agregar el factor de Gas sintetico.
- Manejar fuente sin factor de emision.

#### RF49/50 - Restricciones Cloud y Diesel

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Bloquear factores locales al seleccionar Cloud.
- Mostrar candado gris en los controles bloqueados.
- Manejar errores de renderizado.
- Separar horas de red y horas de diesel.
- Rechazar horas de diesel mayores que la duracion total.
- Aplicar el multiplicador de diesel al calculo.

#### RF51/52 - Agua e inmersion

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Calcular litros usando kWh, WUE y WSI.
- Permitir ingreso manual de litros.
- Validar valores absurdos o negativos.
- Aplicar litros igual a cero para inmersion liquida cuando corresponda.
- Implementar ROI grafico de la inmersion.
- Validar compatibilidad del hardware con fluidos.

#### RF53/54 - WSI y empirismo hidrico

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Incorporar WSI como multiplicador de escasez.
- Calcular severidad y mostrar Gota Roja.
- Manejar fallo de color de UI.
- Integrar lectura de flujometro.
- Importar y cruzar CSV hidrico de forma masiva.
- Detectar desincronizacion horaria.

### 3.12 Autenticacion y multiperfil

#### RF55/56 - Login y registro criptografico

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Sustituir contrasenas en texto plano por Argon2, bcrypt o equivalente.
- Validar contrasena con ASCII estricto, minimo 8 caracteres, mayuscula, numero y uno de `@`, `-` o `_`.
- Implementar contador persistente de intentos fallidos.
- Bloquear despues de cinco intentos.
- Restablecer contador tras autenticacion correcta.
- Manejar fallos de la base de datos de bloqueos.
- Prevenir inyeccion y validar entradas.
- Mostrar feedback de validacion en vivo.

#### RF59/44 - Admin y cuotas de usuario

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar elevacion mediante ticket Admin.
- Implementar cambio forzoso de contrasena temporal.
- Validar la bandera temporal y su corrupcion.
- Permitir cuotas de CO2 y USD por perfil.
- Aplicar cuotas en calculos y disyuntores.
- Rechazar topes irrazonables.

### 3.13 Proyectos macro y gestion UI

#### RF57/58 - Consolidados macro

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Consolidar CO2 de todos los modelos de una campana.
- Generar certificado PDF ESG oficial.
- Bloquear o marcar modelos incompletos antes de generar el certificado.
- Consolidar litros de agua.
- Exportar desglose CSV.
- Manejar errores de disco.

#### RF60/61 - Archivar y transferir

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Implementar estado Archivado como solo lectura.
- Bloquear edicion, eliminacion y ejecucion en proyectos archivados.
- Verificar procesos de fondo antes de archivar.
- Reasignar modelos entre proyectos mediante transaccion.
- Recalcular totales de origen y destino.
- Persistir el recalcado aunque ocurra una interrupcion.

#### RF62/63 - Barras de progreso macro

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Calcular porcentaje financiero gastado sobre la cuota real.
- Calcular porcentaje de CO2 gastado sobre la cuota real.
- Mostrar avisos pasivos en 50 y 75 por ciento.
- Manejar presupuesto infinito o sin limite.
- Generar medalla o estrella verde al cerrar el mes.
- No cerrar ni premiar meses incompletos.

#### RF64/65 - Mantencion de plantillas

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Permitir alterar templates mediante operaciones persistentes.
- Detectar proyectos vinculados.
- Mostrar advertencia predictiva en modal cuando corresponda.
- No mostrar alerta cuando no existan proyectos vinculados.
- Implementar soft-delete de templates.
- Manejar falsos positivos de fallas de matriz.
- Implementar contingencia cuando falte RAM.

#### RF66/67 - Exportacion pura y normativa ISO

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Exportar todos los datos matematicos puros sin informacion de presentacion.
- Completar CSV y JSON.
- Implementar modo consola/headless.
- Validar argumentos del shell.
- Usar fechas `YYYY-MM-DD` en la salida normativa.
- Mostrar offset local en UI.
- Usar ISO estricto si el reloj OS es corrupto.

#### RF68/69/70 - Reglas de pantalla y anticolision

**Evaluacion:** [FALTA / CON ERRORES]

**Falta o debe corregirse:**

- Mostrar `Fuente Primaria Operante: [Tipo de Energia]` a partir de datos reales.
- Mostrar desglose modal y tratar empates como Mix Equilibrado.
- Implementar consejos UI pasivos.
- Minimizar logs sin ocultar errores criticos.
- Validar colision entre estados de semaforo.
- Aplicar bordes rojos y jerarquia visual universal.
- Bloquear guardado cuando existan campos obligatorios vacios.

## 4. Prioridades de implementacion

### Prioridad 0 - Seguridad y consistencia

1. Reemplazar contrasenas en texto plano por hashes seguros.
2. Implementar bloqueo por intentos fallidos y control de roles.
3. Validar entradas, limites y umbrales anti-colision.
4. Definir una unica estrategia de persistencia: SQLite local o PostgreSQL.
5. Implementar transacciones, manejo de permisos y logs de excepcion.

### Prioridad 1 - Motor de calculo

1. Crear un servicio de calculo independiente de la UI.
2. Implementar costo, divisas, kWh, PUE, CIF y diesel.
3. Implementar agua con WUE, WSI e inmersion.
4. Implementar Green Score y clasificacion A+.
5. Persistir cada ejecucion y sus variables de entrada.

### Prioridad 2 - Persistencia y operaciones reales

1. Completar CRUD de proyectos, modelos, hardware y templates.
2. Implementar importacion con previsualizacion y validacion.
3. Implementar soft-delete y hard-delete controlados.
4. Implementar archivado, reasignacion y recalcado.
5. Implementar backup y restauracion verificables.

### Prioridad 3 - UI funcional

1. Conectar semaforos y barras a datos reales.
2. Crear comparativa lado a lado.
3. Crear graficos dinamicos y fallback textual.
4. Crear modales, snooze, recomendaciones y abortado real.
5. Mostrar historial, trazabilidad y errores guiados.

### Prioridad 4 - Integraciones y heuristicas

1. Integrar APIs cloud con timeout, cache y fallback.
2. Integrar sensores SNMP/Modbus o simulador equivalente.
3. Agregar notificaciones OS y modo Concentracion.
4. Implementar rightsizing, carbon-aware shifting y capacity planning.
5. Implementar disyuntores financieros y ecologicos.

### Prioridad 5 - Exportacion y calidad

1. Completar PDF ejecutivo, XLSX, CSV y JSON puro.
2. Agregar modo headless.
3. Crear pruebas unitarias para formulas y validaciones.
4. Crear pruebas de integracion para persistencia y exportacion.
5. Crear pruebas de UI para login, semaforos, importacion y permisos.
6. Probar fallos de red, disco, archivos bloqueados, datos corruptos y excepciones OS.

## 5. Criterios de aceptacion global

El proyecto podra marcarse como listo cuando:

- Los calculos no dependan de valores hardcodeados.
- Cada operacion de UI modifique o consulte persistencia real.
- Las contrasenas y API keys no se almacenen en texto plano.
- Las excepciones del checklist tengan mensajes y rutas de recuperacion.
- El historial sea inmutable y trazable.
- Los umbrales y cuotas se validen antes de guardar.
- Los proyectos archivados sean realmente de solo lectura.
- Los reportes contengan los mismos datos que la pantalla.
- Existan pruebas automatizadas para formulas, permisos, excepciones y exportaciones.
- La aplicacion pueda ejecutarse sin depender de datos estaticos no validados.
