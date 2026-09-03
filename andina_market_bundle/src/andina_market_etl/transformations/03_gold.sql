-- 1. DIMENSIÓN CLIENTES (SCD TIPO 2 - HISTORIAL DE CAMBIOS)
-- Se usa una Streaming Table en vez de una MV, ya que las Materialized Views sobrescriben datos, por lo tanto no nos permiten mantener un historial
-------------------------------------------------------------------------------
CREATE OR REFRESH STREAMING TABLE andina_market.gold.dim_customer
  COMMENT "Dimensión de clientes con historial de cambios (SCD Type 2) en Segmento, Ciudad y País";

CREATE FLOW dim_customer_scd2_flow AS
AUTO CDC INTO andina_market.gold.dim_customer -- Target table
FROM STREAM(andina_market.silver.customers) -- Stream de bronze (source table)
KEYS (CustomerID) -- Usa CustomerID para saber qué fila actualizar
SEQUENCE BY UpdatedAt -- Usa UpdatedAt para saber el orden de los cambios
COLUMNS * EXCEPT (_processed_at, _ingested_at)
STORED AS SCD TYPE 2;


-------------------------------------------------------------------------------
-- 1. dim_customer_current (VERSIÓN VIGENTE PARA POWER BI)
-------------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.dim_customer_current
  COMMENT "Una fila por cliente (versión vigente). Usar para relaciones 1:N en Power BI."
AS SELECT
  CustomerID,
  FullName,
  Email,
  Phone,
  City,
  Country,
  Segment,
  SignupDate
FROM andina_market.gold.dim_customer
WHERE __END_AT IS NULL; -- Solo registros activos


-------------------------------------------------------------------------------
-- 2. DIMENSIÓN PRODUCTOS (SCD TIPO 1 / MATERIALIZED VIEW)
-------------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.dim_product
  COMMENT "Dimensión de productos limpios para el modelo estrella"
AS SELECT
  ProductID,
  SKU,
  ProductName,
  Category,
  Description,
  UnitPrice AS CurrentUnitPrice,
  Status,
  CreatedAt,
  UpdatedAt
FROM andina_market.silver.products;


-------------------------------------------------------------------------------
-- 3. DIMENSIÓN FECHA (DIM_DATE)
-------------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.dim_date
  COMMENT "Tabla de dimensión de fechas para análisis temporal"
AS
-- Genera un rango de fechas desde 2020-01-01 hasta 2030-12-31 (una fila por día)
WITH date_range AS (
  SELECT explode(sequence(to_date('2020-01-01'), to_date('2030-12-31'), interval 1 day)) AS Date
)
SELECT
  CAST(date_format(Date, 'yyyyMMdd') AS INT) AS DateSK,
  Date,
  year(Date) AS Year,
  quarter(Date) AS Quarter,
  month(Date) AS Month,
  date_format(Date, 'MMMM') AS MonthName,
  day(Date) AS Day,
  dayofweek(Date) AS DayOfWeek,
  date_format(Date, 'EEEE') AS DayName,
  CASE WHEN dayofweek(Date) IN (1, 7) THEN true ELSE false END AS IsWeekend
FROM date_range;


-------------------------------------------------------------------------------
-- 4. TABLA DE HECHOS: ÓRDENES E ÍTEMS (FACT_ORDERS)
-------------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.fact_orders
  COMMENT "Tabla de hechos consolidada de pedidos e ítems a nivel de detalle"
AS SELECT
  oi.OrderItemID,
  o.OrderID, -- OrderID tendrá duplicados porque un pedido puede tener varios ítems, por eso es usamos OrderItemID como PK
  COALESCE(o.CustomerID, -1) AS CustomerID,
  oi.ProductID,
  COALESCE(CAST(date_format(o.OrderDate, 'yyyyMMdd') AS INT), -1) AS OrderDateSK,
  o.OrderDate,
  o.Channel,
  o.Status AS OrderStatus,
  oi.Quantity,
  oi.UnitPrice AS HistoricalUnitPrice, -- Guardar el precio al que se vendió, por si el día de mañana cambia (no usar UnitPrice desde dim_product)
  ROUND((oi.Quantity * oi.UnitPrice), 2) AS LineTotalAmount,
  o.TotalAmount AS OrderTotalAmount,
  o.CreatedAt
FROM andina_market.silver.orders o
INNER JOIN andina_market.silver.order_items oi
  ON o.OrderID = oi.OrderID;


-------------------------------------------------------------------------------
-- 5. TABLA DE HECHOS: PAGOS (FACT_PAYMENTS)
-------------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.fact_payments
  COMMENT "Tabla de hechos de transacciones de pago"
AS SELECT
  PaymentID,
  OrderID,
  COALESCE(CAST(date_format(PaymentDate, 'yyyyMMdd') AS INT), -1) AS PaymentDateSK,
  PaymentDate,
  PaymentMethod,
  Amount,
  Status AS PaymentStatus,
  CreatedAt
FROM andina_market.silver.payments;


-------------------------------------------------------------------------------
-- 6. TABLA DE HECHOS: TICKETS DE SOPORTE (FACT_SUPPORT_TICKETS)
-------------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.fact_support_tickets
  COMMENT "Tabla de hechos de atención al cliente y tickets de soporte"
AS SELECT
  TicketID,
  COALESCE(CustomerID, -1) AS CustomerID,
  COALESCE(CAST(date_format(CreatedAt, 'yyyyMMdd') AS INT), -1) AS CreatedDateSK,
  CreatedAt,
  UpdatedAt,
  Subject,
  Status AS TicketStatus,
  Priority,
  CASE 
  -- Tiempo de resolución en días
    WHEN UpdatedAt IS NOT NULL AND Status IN ('Closed', 'Resolved') THEN ROUND(CAST((unix_timestamp(UpdatedAt) - unix_timestamp(CreatedAt)) AS DOUBLE) / 86400.0, 2)
    ELSE NULL 
  END AS ResolutionTimeDays
FROM andina_market.silver.support_tickets;