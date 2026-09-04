-- deduped: CTE para deduplicar
-- cleaned: CTE para limpiar datos, selecciona desde deduped

-- Streaming Table en vez de Materialized View para SCD
-- AUTO CDC en gold.dim_customer manejará duplicados con SEQUENCE BY UpdatedAt

CREATE OR REFRESH STREAMING TABLE andina_market.silver.customers 
(
    CONSTRAINT valid_customer_id EXPECT (CustomerID IS NOT NULL) ON VIOLATION DROP ROW,
    CONSTRAINT valid_email_format EXPECT (Email IS NULL OR Email LIKE '%@%.%')
)
AS
SELECT
    CustomerID,
    INITCAP(TRIM(FullName)) AS FullName,
    NULLIF(LOWER(TRIM(Email)), '') AS Email,
    
    CASE
  -- 1. Descartar nulos, vacíos o números con menos de 7 dígitos
        WHEN Phone IS NULL OR TRIM(Phone) = '' THEN NULL
        WHEN LENGTH(REGEXP_REPLACE(Phone, '[^0-9]', '')) < 7 THEN NULL

        -- 2. Si ya empieza con '+', limpiamos espacios o guiones internos pero conservamos el '+'
        WHEN TRIM(Phone) LIKE '+%' THEN CONCAT('+', REGEXP_REPLACE(Phone, '[^0-9]', ''))

        -- 3. Si empieza con '00' (prefijo internacional estándar), lo reemplazamos por '+'
        WHEN TRIM(Phone) LIKE '00%' THEN CONCAT('+', REGEXP_REPLACE(SUBSTRING(TRIM(Phone), 3), '[^0-9]', ''))

        -- 4. Si es un número sin prefijo (ej: 3113164752), solo conservamos los dígitos
        ELSE REGEXP_REPLACE(Phone, '[^0-9]', '')
        END AS Phone,

    City,
    CASE
        WHEN UPPER(TRIM(Country)) IN ('PE', 'PERU')       THEN 'Peru'
        WHEN UPPER(TRIM(Country)) IN ('CO', 'COLOMBIA')   THEN 'Colombia'
        WHEN UPPER(TRIM(Country)) IN ('MX', 'MEXICO')     THEN 'Mexico'
        WHEN UPPER(TRIM(Country)) IN ('CL', 'CHILE')      THEN 'Chile'
        WHEN UPPER(TRIM(Country)) IN ('AR', 'ARGENTINA')  THEN 'Argentina'
        WHEN Country IS NULL                              THEN NULL
        ELSE INITCAP(TRIM(Country))
    END AS Country,
    CASE
        WHEN UPPER(TRIM(Segment)) = 'REGULAR' THEN 'Regular'
        WHEN UPPER(TRIM(Segment)) = 'VIP'     THEN 'VIP'
        WHEN UPPER(TRIM(Segment)) = 'PREMIUM' THEN 'Premium'
        ELSE NULL
    END AS Segment,
    SignupDate,
    CreatedAt,
    UpdatedAt,
    _ingested_at,
    CURRENT_TIMESTAMP() AS _processed_at
FROM STREAM(andina_market.bronze.customers);

--  Products

CREATE OR REFRESH MATERIALIZED VIEW 
    andina_market.silver.products 
(
    CONSTRAINT valid_product_id EXPECT (ProductID IS NOT NULL) ON VIOLATION DROP ROW,
    CONSTRAINT non_negative_price EXPECT (UnitPrice IS NULL OR UnitPrice >= 0)
)
AS
WITH deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY ProductID
            ORDER BY _ingested_at DESC, UpdatedAt DESC
        ) AS row_num
    FROM andina_market.bronze.products
    WHERE ProductID IS NOT NULL
),
cleaned AS (
    SELECT
        ProductID,
        SKU,
        INITCAP(TRIM(ProductName)) AS ProductName,
        CASE 
            WHEN LOWER(TRIM(Category)) IN ('deportes', 'deporte') THEN 'Deportes'
            WHEN LOWER(TRIM(Category)) IN ('juguetes', 'juguete') THEN 'Juguetes'
            WHEN LOWER(TRIM(Category)) IN ('electronica') THEN 'Electrónica'
            WHEN LOWER(TRIM(Category)) IN ('hogar') THEN 'Hogar'
            WHEN LOWER(TRIM(Category)) IN ('moda') THEN 'Moda'
            WHEN LOWER(TRIM(Category)) IN ('belleza') THEN 'Belleza'
            WHEN LOWER(TRIM(Category)) IN ('libros') THEN 'Libros'
            ELSE INITCAP(TRIM(Category))
        END AS Category,
        Description,
        -- Precio negativo es un error de captura sin forma de inferir el
        -- valor real -> se anula y se marca con flag en vez de adivinar
        CASE WHEN UnitPrice < 0 THEN NULL ELSE UnitPrice END AS UnitPrice,
        CASE WHEN UnitPrice < 0 THEN TRUE ELSE FALSE END AS had_invalid_price,
        CASE
            WHEN UPPER(TRIM(Status)) IN ('ACTIVE') THEN 'Active'
            WHEN UPPER(TRIM(Status)) IN ('DISCONTINUED', 'DISC') THEN 'Discontinued'
            ELSE NULL
        END AS Status,
        CreatedAt,
        UpdatedAt,
        _ingested_at,
        CURRENT_TIMESTAMP() AS _processed_at
    FROM deduped 
    WHERE row_num = 1
)
SELECT * FROM cleaned;

-- Orders

CREATE OR REFRESH MATERIALIZED VIEW andina_market.silver.orders 
(
    CONSTRAINT valid_order_id EXPECT (OrderID IS NOT NULL) ON VIOLATION DROP ROW,
    CONSTRAINT valid_customer_reference EXPECT (CustomerID IS NOT NULL),
    CONSTRAINT non_negative_total EXPECT (TotalAmount IS NULL OR TotalAmount >= 0)
)
AS
WITH deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY OrderID
            ORDER BY _ingested_at DESC
        ) AS row_num
    FROM andina_market.bronze.orders
    WHERE OrderID IS NOT NULL
),
cleaned AS (
    SELECT
        o.OrderID,
        o.CustomerID,
        o.OrderDate,
        CASE
            -- Reemplazar guiónes por espacios simples, eliminar espacios al inicio y final, y normalizar / capitalizar
            WHEN UPPER(TRIM(REPLACE(o.Channel, '_', ' '))) = 'WEB' THEN 'Web'
            WHEN UPPER(TRIM(REPLACE(o.Channel, '_', ' '))) = 'APP' THEN 'App'
            WHEN UPPER(TRIM(REPLACE(o.Channel, '_', ' '))) IN ('TIENDA', 'TIENDA FISICA') THEN 'Tienda'
            ELSE NULL
        END AS Channel,
        CASE
            WHEN UPPER(TRIM(o.Status)) = 'PENDING'    THEN 'Pending'
            WHEN UPPER(TRIM(o.Status)) = 'COMPLETED'  THEN 'Completed'
            WHEN UPPER(TRIM(o.Status)) = 'CANCELLED'  THEN 'Cancelled'
            WHEN UPPER(TRIM(o.Status)) = 'SHIPPED'    THEN 'Shipped'
            ELSE NULL
        END AS Status,
        o.TotalAmount,
        o.CreatedAt,
        o.UpdatedAt,
        o._ingested_at,
        CURRENT_TIMESTAMP() AS _processed_at
    FROM deduped o
    WHERE row_num = 1
)
SELECT
    c.OrderID,
    c.CustomerID,
    c.OrderDate,
    c.Channel,
    c.Status,
    c.TotalAmount,
    c.CreatedAt,
    c.UpdatedAt,
    c._ingested_at,
    c._processed_at
FROM cleaned c
-- Solo se conservan órdenes cuyo CustomerID existe en silver.customers ya limpio
-- Se deduplica customers para evitar fan-out: la streaming table puede tener
-- multiples versiones del mismo cliente y un JOIN directo multiplicaria las ordenes
INNER JOIN (
    SELECT DISTINCT CustomerID
    FROM andina_market.silver.customers
) cust
    ON c.CustomerID = cust.CustomerID;

-- Order Items

CREATE OR REFRESH MATERIALIZED VIEW andina_market.silver.order_items 
(
    CONSTRAINT valid_order_item_id EXPECT (OrderItemID IS NOT NULL) ON VIOLATION DROP ROW,
    CONSTRAINT valid_quantity EXPECT (Quantity > 0) ON VIOLATION DROP ROW,
    CONSTRAINT valid_unit_price EXPECT (UnitPrice IS NULL OR UnitPrice > 0)
)
AS
WITH deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY OrderItemID
            ORDER BY _ingested_at DESC
        ) AS row_num
    FROM andina_market.bronze.order_items
    WHERE OrderItemID IS NOT NULL
),
cleaned AS (
    SELECT *
    FROM deduped
    WHERE row_num = 1
)
SELECT
    c.OrderItemID,
    c.OrderID,
    c.ProductID,
    c.Quantity,
    c.UnitPrice,
    c.CreatedAt,
    c._ingested_at,
    CURRENT_TIMESTAMP() AS _processed_at
FROM cleaned c
-- Solo líneas cuyo pedido y producto existen en sus respectivas silver, y
-- con cantidad válida (0 o negativa no tiene interpretación de negocio)
INNER JOIN andina_market.silver.orders ord ON c.OrderID = ord.OrderID
INNER JOIN andina_market.silver.products prod ON c.ProductID = prod.ProductID
WHERE c.Quantity > 0;

-- Payments

CREATE OR REFRESH MATERIALIZED VIEW andina_market.silver.payments 
(
    CONSTRAINT valid_payment_id EXPECT (PaymentID IS NOT NULL) ON VIOLATION DROP ROW,
    CONSTRAINT valid_amount EXPECT (Amount IS NULL OR Amount >= 0)
)
AS
WITH deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY PaymentID
            ORDER BY _ingested_at DESC
        ) AS row_num
    FROM andina_market.bronze.payments
    WHERE PaymentID IS NOT NULL
),
cleaned AS (
    SELECT *
    FROM deduped
    WHERE row_num = 1
)
SELECT
    c.PaymentID,
    c.OrderID,
    CASE
        WHEN UPPER(TRIM(REPLACE(c.PaymentMethod, '_', ' '))) = 'CREDIT CARD' THEN 'Credit Card'
        WHEN UPPER(TRIM(REPLACE(c.PaymentMethod, '_', ' '))) = 'DEBIT CARD'  THEN 'Debit Card'
        WHEN UPPER(TRIM(REPLACE(c.PaymentMethod, '_', ' '))) = 'PAYPAL'      THEN 'PayPal'
        WHEN UPPER(TRIM(REPLACE(c.PaymentMethod, '_', ' '))) IN ('CASH', 'EFECTIVO') THEN 'Cash'
        ELSE NULL
    END AS PaymentMethod,
    c.Amount,
    CASE
        WHEN UPPER(TRIM(c.Status)) = 'APPROVED' THEN 'Approved'
        WHEN UPPER(TRIM(c.Status)) = 'PENDING'  THEN 'Pending'
        WHEN UPPER(TRIM(c.Status)) = 'FAILED'   THEN 'Failed'
        WHEN UPPER(TRIM(c.Status)) = 'REFUNDED' THEN 'Refunded'
        ELSE NULL
    END AS Status,
    c.PaymentDate,
    c.CreatedAt,
    c.UpdatedAt,
    -- Se conservan intentos múltiples de pago sobre un mismo pedido
    -- (reintentos legítimos), pero se numeran para trazabilidad
    ROW_NUMBER() OVER (
        PARTITION BY c.OrderID ORDER BY c.CreatedAt ASC
    ) AS payment_attempt_number,
    CASE
        WHEN ABS(c.Amount - ord.TotalAmount) > 0.01 THEN TRUE
        ELSE FALSE
    END AS amount_mismatch_flag,
    c._ingested_at,
    CURRENT_TIMESTAMP() AS _processed_at
FROM cleaned c
INNER JOIN andina_market.silver.orders ord
    ON c.OrderID = ord.OrderID;

-- Support Tickets

CREATE OR REFRESH MATERIALIZED VIEW andina_market.silver.support_tickets 
(
    CONSTRAINT valid_ticket_id EXPECT (TicketID IS NOT NULL) ON VIOLATION DROP ROW
)
AS
WITH deduped AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY TicketID
            ORDER BY _ingested_at DESC
        ) AS row_num
    FROM andina_market.bronze.support_tickets
    WHERE TicketID IS NOT NULL
),
cleaned AS (
    SELECT *
    FROM deduped
    WHERE row_num = 1
)
SELECT
    c.TicketID,
    c.CustomerID,
    c.Subject,
    c.Body,
    CASE
        WHEN UPPER(TRIM(REPLACE(c.Status, '_', ' '))) = 'OPEN'         THEN 'Open'
        WHEN UPPER(TRIM(REPLACE(c.Status, '_', ' '))) = 'IN PROGRESS'  THEN 'In Progress'
        WHEN UPPER(TRIM(REPLACE(c.Status, '_', ' '))) = 'CLOSED'       THEN 'Closed'
        ELSE NULL
    END AS Status,
    CASE
        WHEN UPPER(TRIM(c.Priority)) = 'LOW'                           THEN 'Low'
        WHEN UPPER(TRIM(c.Priority)) = 'MEDIUM'                        THEN 'Medium'
        WHEN UPPER(TRIM(c.Priority)) IN ('HIGH', 'URGENTE', 'ALTA')    THEN 'High'
        ELSE NULL
    END AS Priority,
    c.CreatedAt,
    c.UpdatedAt,
    c._ingested_at,
    CURRENT_TIMESTAMP() AS _processed_at
FROM cleaned c
-- Retiene únicamente aquellos tickets cuyo CustomerID exista en la tabla silver.customers
-- Se deduplica customers para evitar fan-out: la streaming table puede tener
-- multiples versiones del mismo cliente y un JOIN directo multiplicaria los tickets
INNER JOIN (
    SELECT DISTINCT CustomerID
    FROM andina_market.silver.customers
) cust
    ON c.CustomerID = cust.CustomerID;