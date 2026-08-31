# Andina Market — Reto Técnico Ingeniero(a) de Datos

Pipeline de datos end-to-end para Andina Market (retailer ficticio de e-commerce
Latam), desde ingesta hasta capa de analítica, construido sobre **Databricks
Free Edition** con arquitectura **medallion** (Bronze → Silver → Gold) y
desplegado como **Databricks Automation Bundle**.

## Nivel alcanzado

- [x] **Nivel 1 — Ingesta ☑**
- [x] **Nivel 2 — Transformación y modelado ☑**
- [x] **Nivel 3 — Gold / Modelado + visualización ☑**
- [ ] Nivel 4 — Feature Store
- [ ] Nivel 5 — Capa RAG
- [ ] Nivel 6 — Agentes GenAI

---

## 1. Arquitectura

**Diagrama:** ver `docs/architecture-diagram.png`.

**Resumen:**

![](/Workspace/Users/cornachofrance@gmail.com/andina_market/docs/architecture_diagram.png)

**Por qué esta arquitectura:**

![](/Workspace/Users/cornachofrance@gmail.com/andina_market/docs/etl_succeded.png)

- **Medallion (Bronze/Silver/Gold)** porque separa claramente "dato crudo tal
  como llegó" (auditable, reprocesable) de "dato validado" de "dato modelado
  para negocio" — cada capa tiene una responsabilidad y un dueño claro.

- **Un único catálogo (`andina_market`) con 3 schemas** (`bronze`,
  `silver`, `gold`) en vez de catálogos separados por capa: a esta escala
  (proyecto individual, dataset sintético pequeño) separar por catálogo agrega
  complejidad operativa sin beneficio real de gobernanza.

- **Gold vive en Delta dentro del mismo catálogo**, no en un motor de
  warehouse aparte — se construye con notebooks Spark, así que lo natural es
  que escriba en el mismo formato que ya domina esa capa de cómputo.

---

## 2. Fuente de datos

Como el reto no provee un script DDL real ni una base de datos con datos ya
cargados, se generó todo el esquema origen y los datos sintéticos:

- **`reto/data_generator.py`**: genera las 6 tablas de origen (`Customers`,
  `Products`, `Orders`, `OrderItems`, `Payments`, `SupportTickets`) con datos
  sintéticos realistas (librería Faker) e **inyecta errores de calidad de
  datos a propósito** (duplicados, nulos, inconsistencias de formato,
  registros huérfanos, montos que no cuadran, etc.) para tener trabajo real
  de limpieza que resolver en Silver. El detalle de cada error inyectado y su
  probabilidad está documentado como comentarios en el propio script.

- El esquema de las tablas origen (columnas, tipos, PKs) se diseñó a partir
  de la descripción de la sección 2 del brief del reto — no existe un DDL
  oficial provisto por Talento Para Ti. Ver `reto/sql/create_tables.sql` para el script de creación
  de tablas y el diagrama entidad-relación.

### Limitación de conectividad: por qué se usa CSV en vez de Azure SQL

El plan original era ingerir directo desde una Azure SQL Database vía JDBC. 

**Databricks Free Edition restringe
el tráfico de red saliente a un conjunto limitado de dominios de confianza**,
lo que en la práctica bloqueó la conexión JDBC. 

**Solución adoptada:** `data_generator.py` escribe los datos generados como
CSV en un **Volume de Unity Catalog** (`andina_source.landing`), que actúa
como "landing zone" — simula el resultado de un export/extract de la fuente
real. La ingesta de Bronze lee de ahí en vez de hacer JDBC en vivo, pero
**conserva la misma lógica de ingesta incremental por watermark** que se
usaría contra la base de datos real (ver más abajo). El código de la versión
JDBC real se conserva en el repo, comentado, como evidencia de que la
arquitectura "correcta" fue diseñada y no reemplazada por desconocimiento.

---

## 3. Nivel 1 — Ingesta (Bronze)

**Decisiones:**

- **Ingesta incremental por watermark**, no full load. Columna de referencia:
  `UpdatedAt` para la mayoría de tablas; `CreatedAt` para `OrderItems` (no
  tiene `UpdatedAt` en el diseño de origen, es un detalle inmutable de línea
  de pedido).

- **`Payments` es el caso clave**: un pago cambia de estado *después* de
  creado el pedido, por eso su columna de auditoría `UpdatedAt` es la que
  determina qué se re-ingiere en cada corrida — sin ella, cambios de estado
  posteriores (aprobado → reembolsado, por ejemplo) nunca se capturarían.

- **`mode("append")` en Bronze**, no overwrite: Bronze acumula todas las
  versiones de una fila a lo largo del tiempo (si una carga no fue
  idempotente, puede haber PKs repetidos). Esta es una decisión deliberada:
  **Silver es quien deduplica** (por PK, quedándose con la versión más
  reciente por `_ingested_at`), no Bronze. Bronze debe ser la fuente de
  verdad cruda, nunca se "limpia" ahí.

- **`mergeSchema = true`**: respuesta a "qué haces si cambia el esquema de
  origen" — nuevas columnas en el origen no rompen la carga, se absorben
  automáticamente. Cambios incompatibles (tipo de dato, columna eliminada)
  sí requerirían intervención manual — no hay mitigación automática para eso
  en este alcance.

- **`_ingested_at`** se agrega en cada fila como timestamp de auditoría/
  trazabilidad de cuándo llegó cada dato a Bronze.

**Extensión de diseño (solo diseño, no implementado):**

- **Streaming del clickstream**: ver `docs/streaming-design.md`. Propuesta:
  Event Hubs/Kafka como buffer de ingesta en tiempo real → Structured
  Streaming
  con checkpointing → append a Bronze en modo streaming, misma capa de Silver
  aguas abajo sin cambios.

- **Integración con SAP ECC on-premise**: ver `docs/sap-integration-design.md`.

---

## 4. Nivel 2 — Transformación y modelado (Silver)

**Patrón aplicado a las 6 tablas** (ver el archivo de Silver en
`andina_market (bundle)/src/andina_market_etl`):

1. **Estandarizar categóricos**: cada campo de texto libre (`Channel`,
   `Status`, `PaymentMethod`, `Segment`, `Priority`, `Country`, etc.) se
   mapea explícitamente a un valor canónico vía `CASE`. Si un valor no
   matchea ninguna variante conocida, se deja `NULL` — no se inventa un
   default no justificable.

2. **Deduplicar solo por PK** (`ROW_NUMBER() OVER (PARTITION BY <PK> ORDER BY
   _ingested_at DESC)`), nunca por atributos de negocio como email — email
   duplicado es una señal de calidad de datos, no evidencia de que dos
   `CustomerID` sean la misma persona.

3. **Integridad referencial vía `INNER JOIN` contra la tabla padre ya
   limpia**: una fila hija solo pasa a Silver si su padre ya existe en la
   versión limpia — así el filtro de huérfanos se propaga en cascada
   (Customers → Orders → OrderItems/Payments/SupportTickets).

**Casos particulares documentados:**
- Pedidos **sin** pago asociado no se tratan como error — es un estado de
  negocio válido (pago pendiente).

- Pagos duplicados sobre un mismo pedido no se descartan — se numeran
  (`payment_attempt_number`) como reintentos legítimos.

- SKU duplicado en `Products` se deja pasar — no es un error de llave
  primaria, es una métrica de calidad de catálogo aparte.

---

## 5. Nivel 3 — Gold + visualización

### 5.1 Modelo dimensional (star schema)

Construido con notebook (PySpark/Spark SQL), no un script SQL plano — el
notebook vive en `andina_market (bundle)/src/`.

| Tabla | Tipo | Notas |
|---|---|---|
| `dim_customer` | **SCD Tipo 2** | Historiza cambios de `Segment`/`City`/`Country`/etc. vía `MERGE` de Delta Lake (patrón estándar de 2 pasos: cerrar versión vigente + insertar nueva). Es el caso que el reto pide explícitamente (cliente que cambia de segmento). |
| `dim_product` | SCD Tipo 1 | Full refresh cada corrida — decisión consciente de alcance, no se historiza cambio de precio/categoría. |
| `dim_date` | Calendario | Generado desde el rango real de fechas de negocio, no hardcodeado. |
| `fact_orders` | Grano: 1 fila por pedido | Join **temporal** contra `dim_customer` (`OrderDate` entre `EffectiveDate`/`ExpirationDate`) — cada pedido se atribuye al segmento/ciudad vigente del cliente *en ese momento*, no al actual. |
| `fact_order_items` | Grano: 1 fila por línea de pedido | |
| `fact_payments` | Grano: 1 fila por pago | Incluye reintentos numerados. |
| `fact_support_tickets` | Grano: 1 fila por ticket | Incluye `DaysToUpdate` como base para KPI de resolución. |

### 5.2 Conexión Power BI → Databricks

Get Data → conector **Databricks** → `Server Hostname` + `HTTP Path` del SQL
Warehouse (Free Edition incluye uno serverless por defecto) → autenticación
con Personal Access Token / OAuth. Modo **Import** (no DirectQuery): el
volumen de datos es pequeño y Import da mejor performance interactiva sin
depender de que el warehouse esté siempre activo mientras alguien navega el
dashboard.

### 5.3 KPIs del dashboard

### KPIs principales

| KPI | Tipo de visual | Tabla(s) / medida |
|---|---|---|
| Ingresos Totales | Card | `SUM(fact_orders[TotalAmount])` |
| Ticket Promedio por Orden (AOV) | Card | `DIVIDE([Ingresos Totales], DISTINCTCOUNT(fact_orders[OrderID]))` |
| Días Promedio de Resolución de Tickets | Card | `AVERAGE(fact_support_tickets[DaysToUpdate])` |
| Órdenes Totales | Card | `DISTINCTCOUNT(fact_orders[OrderID])` |
| Tickets de Soporte Abiertos | Card | `COUNT(fact_support_tickets[TicketID])` filtrado por `Status = "Open"` |

### Visualizaciones de soporte

| Visual | Tipo de gráfico | Tabla(s) / medida |
|---|---|---|
| Ingresos por Canal de Venta | Gráfico de torta | `fact_orders[Channel]` × `SUM(TotalAmount)` |
| Ingresos por Mes | Línea | `dim_date[Month]` × `SUM(TotalAmount)` |
| Ingresos por Año | Línea | `dim_date[Year]` × `SUM(TotalAmount)` |
| Clientes por País | Barras | `dim_customer[Country]` × `COUNT(CustomerID)` |
| Clientes por Segmento | Torta | `dim_customer[Segment]` × `COUNT(CustomerID)` |
| 10 Productos Más Vendidos | Barras horizontales | `dim_product[ProductName]` × `SUM(fact_order_items[Quantity])` |
| Órdenes por Categoría | Barras | `dim_product[Category]` × `DISTINCTCOUNT(OrderID)` |

### 5.4 Refresco del dashboard

Programado como tarea
dentro del Job de Databricks que orquesta todo el pipeline

![](/Workspace/Users/cornachofrance@gmail.com/andina_market/docs/job_succeded.png)

![](/Workspace/Users/cornachofrance@gmail.com/andina_market/docs/refresh_dashboard.png)

---

## 6. Estructura del repositorio

```
andina_market/
├── andina_market (bundle)/       Databricks Asset Bundle
│   ├── resources/                 Definición del Job y Pipeline (YAML)
│   ├── src/                       Notebooks: ingesta Bronze, transformación
│   │                              Silver, modelado Gold
│   ├── databricks.yml              Config raíz del bundle (target, workspace)
│   └── README.md                  Notas específicas del bundle
├── reto/
│   └── data_generator.py          Generador de datos sintéticos + carga
├── docs/                          Diagramas de arquitectura y ER,
│                                   diseño de streaming y SAP (Nivel 1 ext.)
└── README.md                      Este archivo
```

---

## 7. Cómo reproducir / correr el proyecto

Prerrequisitos: [Databricks CLI](https://docs.databricks.com/dev-tools/cli/index.html)
instalado (`databricks -v` para confirmar), y acceso a un workspace de
Databricks (Free Edition sirve).

```bash
# 1. Autenticarte contra tu workspace
databricks configure --host <tu-workspace-url>
# o, si usas OAuth: databricks auth login --host <tu-workspace-url>

# 2. Desde andina_market (bundle)/, validar que el bundle esté bien formado
cd "andina_market (bundle)"
databricks bundle validate

# 3. Desplegar los recursos (Job, Pipeline, notebooks) al workspace
databricks bundle deploy -t dev

# 4. Generar los datos sintéticos (landing zone) -- una sola vez, o cuando
#    quieras refrescar el dataset base
python ../reto/data_generator.py

# 5. Correr el pipeline completo (Bronze -> Silver -> Gold)
databricks bundle run andina_market_job
```

Una vez corrido, las tablas quedan disponibles en Unity Catalog bajo
`andina_market.bronze`, `andina_market.silver` y `andina_market.gold`, listas
para conectar Power BI como se describe en la sección 5.2.

---

## 8. Supuestos declarados

- El esquema de las tablas origen (Azure SQL) fue diseñado por mí a partir de
  la descripción del brief (sección 2 del PDF), incluyendo columnas de
  auditoría (`CreatedAt`/`UpdatedAt`) no mencionadas explícitamente pero
  necesarias para justificar la estrategia de ingesta incremental del Nivel 1.

- Las FKs del esquema origen existen (para que herramientas de ER las
  detecten) pero están deshabilitadas (`NOCHECK CONSTRAINT ALL`) a propósito,
  simulando deuda técnica de un sistema legacy — de ahí salen los huérfanos
  que Silver cuarentena.

- Por restricciones de red de Databricks Free Edition, la ingesta de Bronze
  lee desde CSVs en un Volume de Unity Catalog en vez de una conexión JDBC en
  vivo a Azure SQL. La lógica de incremental/watermark se conserva igual.

- `dim_customer` es la única dimensión con SCD Tipo 2 real; `dim_product` usa
  Tipo 1 (full refresh) por alcance — no se historiza cambio de precio.

- Todos los datos son 100% sintéticos, generados con Faker.

---

## 9. Desafíos técnicos y decisiones de alcance


- **Conectividad a Azure SQL bloqueada** en Databricks Free Edition. Resuelto con el
  patrón de landing CSV descrito en la sección 2.

- **Nivel 5 (RAG) se intentó pero no se completó**: se avanzó con chunking,
  embeddings y un índice de Vector Search funcional, pero la integración
  final de generación (LLM) presentó inestabilidad del lado de los endpoints
  de Foundation Model APIs del tier gratuito. Se decidió priorizar
  profundidad en los Niveles 1-3 (núcleo + Gold/visualización) por sobre un
  Nivel 5 incompleto, siguiendo el criterio que el propio brief del reto
  establece: *"preferimos ver dos niveles resueltos con criterio sólido que
  cinco niveles resueltos de forma superficial"*.

---

## 10. Uso de asistentes de IA

Este proyecto usó **Claude** (Anthropic) como copiloto de diseño y código a
lo largo del desarrollo — generación de datos sintéticos, debugging de
errores de plataforma, y redacción de
transformaciones SQL/PySpark. Declarado con honestidad según lo permitido en
la sección 13 del brief del reto.