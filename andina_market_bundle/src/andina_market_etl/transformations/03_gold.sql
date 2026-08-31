-- 1. DIMENSIÓN CLIENTES (SCD TIPO 2 - HISTORIAL DE CAMBIOS)
-------------------------------------------------------------------------------
-- Declaramos la Streaming Table de destino en la capa Gold
CREATE OR REFRESH STREAMING TABLE andina_market.gold.dim_customer
  COMMENT "Dimensión de clientes con historial de cambios (SCD Type 2) en Segmento, Ciudad y País";

-- Flujo CDC automático que gestiona las fechas e IsCurrent por detrás
CREATE FLOW dim_customer_scd2_flow AS
AUTO CDC INTO andina_market.gold.dim_customer
FROM STREAM(andina_market.silver.customers)
KEYS (CustomerID)
SEQUENCE BY UpdatedAt -- Columna de timestamp usada para ordenar los eventos y resolver qué cambio ocurrió primero
COLUMNS * EXCEPT (_processed_at, _ingested_at) -- No son necesarias en gold
STORED AS SCD TYPE 2;


-------------------------------------------------------------------------------
-- 1b. dim_customer_current -- una sola fila por cliente (version vigente)
-------------------------------------------------------------------------------
-- dim_customer tiene MULTIPLES filas por CustomerID (una por version
-- historica) -- eso rompe una relacion 1:muchos limpia en Power BI, que
-- necesita una llave unica del lado "1". Esta vista expone solo la version
-- vigente (__END_AT IS NULL), una fila por cliente. USAR ESTA para la
-- relacion del modelo semantico en Power BI, no dim_customer directo.
-- dim_customer (arriba) sigue siendo la fuente de verdad historica, usada
-- por fact_orders para atribuir cada pedido al cliente tal como era en
-- ese momento (ver mas abajo).
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.dim_customer_current
  COMMENT "Una fila por cliente -- la version vigente. Usar para relaciones en Power BI."
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
WHERE __END_AT IS NULL;


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
  UnitPrice,
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
WITH date_range AS (
  SELECT explode(sequence(to_date('2020-01-01'), to_date('2030-12-31'), interval 1 day)) AS Date
)
SELECT
  year(Date) * 10000 + month(Date) * 100 + day(Date) AS DateSK,
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
-- Se agrega un LEFT JOIN temporal contra dim_customer (la historica, no
-- dim_customer_current) para traer el Segmento/Ciudad/Pais que el cliente
-- TENIA al momento del pedido -- es lo que hace que el SCD2 realmente se
-- use en algun lado, no solo exista en Gold sin conectarse a nada.
-- Es LEFT JOIN (no INNER) porque la integridad referencial ya se garantizo
-- en Silver -- si por algun caso limite no hay match, se prefiere conservar
-- la fila del pedido con estos 3 campos en NULL antes que perderla.
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.fact_orders
  COMMENT "Tabla de hechos consolidada de pedidos e ítems a nivel de detalle"
AS SELECT
  oi.OrderItemID,
  o.OrderID,
  o.CustomerID,
  oi.ProductID,
  year(o.OrderDate) * 10000 + month(o.OrderDate) * 100 + day(o.OrderDate) AS OrderDateSK,
  o.OrderDate,
  o.Channel,
  o.Status AS OrderStatus,
  oi.Quantity,
  oi.UnitPrice,
  (oi.Quantity * oi.UnitPrice) AS LineTotalAmount,
  o.TotalAmount AS OrderTotalAmount,
  o.CreatedAt,
  dc.Segment AS CustomerSegmentAtOrderTime,
  dc.City AS CustomerCityAtOrderTime,
  dc.Country AS CustomerCountryAtOrderTime
FROM andina_market.silver.orders o
INNER JOIN andina_market.silver.order_items oi
  ON o.OrderID = oi.OrderID
LEFT JOIN andina_market.gold.dim_customer dc
  ON o.CustomerID = dc.CustomerID
 AND CAST(o.OrderDate AS DATE) >= dc.__START_AT
 AND (dc.__END_AT IS NULL OR CAST(o.OrderDate AS DATE) < dc.__END_AT);


-------------------------------------------------------------------------------
-- 5. TABLA DE HECHOS: PAGOS (FACT_PAYMENTS)
-------------------------------------------------------------------------------
CREATE OR REFRESH MATERIALIZED VIEW andina_market.gold.fact_payments
  COMMENT "Tabla de hechos de transacciones de pago"
AS SELECT
  PaymentID,
  OrderID,
  year(PaymentDate) * 10000 + month(PaymentDate) * 100 + day(PaymentDate) AS PaymentDateSK,
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
  CustomerID,
  year(CreatedAt) * 10000 + month(CreatedAt) * 100 + day(CreatedAt) AS CreatedDateSK,
  CreatedAt,
  UpdatedAt,
  Subject,
  Status AS TicketStatus,
  Priority,
  ROUND(CAST((unix_timestamp(UpdatedAt) - unix_timestamp(CreatedAt)) AS DOUBLE) / 3600.0 / 24.0, 2) AS ResolutionTimeDays
FROM andina_market.silver.support_tickets;