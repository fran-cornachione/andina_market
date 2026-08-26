/* =====================================================================
   ANDINA MARKET — Esquema de origen (Azure SQL Database)
   =====================================================================
   Filosofía de diseño:
   Este NO es un esquema "limpio" de manual. Simula un sistema OLTP
   real con varios años de deuda técnica: constraints laxos, FKs
   deshabilitadas, columnas categóricas como texto libre. La intención
   es generar problemas de calidad de datos REALISTAS que se resuelven
   en la capa Silver, no bugs artificiales sin sentido de negocio.

   Errores/decisiones intencionales (documentados para referencia):
   1. Sin UNIQUE en Email / SKU -> duplicados y variantes de casing.
   2. Columnas categóricas (Channel, Status, PaymentMethod, Segment)
      son VARCHAR libre sin CHECK -> aparecerán variantes tipo
      'web'/'Web'/'WEB', 'tienda_fisica'/'Tienda', etc.
   3. FKs SÍ existen (para que herramientas de introspección/ERD como
      ChartDB las detecten y dibujen la relación) pero se deshabilitan
      con NOCHECK CONSTRAINT ALL al final del script -> simula un caso
      común en sistemas legacy donde la relación "existe" pero no se
      valida en cada insert. Esto produce registros huérfanos reales
      (ej. OrderItems.ProductID que ya no existe).
   4. La mayoría de columnas son NULLable, incluso donde en teoría no
      deberían serlo -> nulls inesperados en campos de negocio clave.
   5. Payments.UpdatedAt existe porque un pago cambia de estado DESPUÉS
      de creado el pedido -> es la pista para tu estrategia de
      ingesta incremental / CDC del Nivel 1.
   6. Orders.TotalAmount se genera de forma independiente a la suma de
      OrderItems -> no siempre van a cuadrar (inconsistencia aritmética
      típica de sistemas mal mantenidos).
   ===================================================================== */

-- =====================================================================
-- 1. dbo.Customers
-- =====================================================================
CREATE TABLE dbo.Customers (
    CustomerID      INT IDENTITY(1,1) PRIMARY KEY,
    FullName        NVARCHAR(200)   NULL,   -- espacios extra, mayúsculas mixtas
    Email           VARCHAR(255)    NULL,   -- sin UNIQUE: habrá duplicados/casing
    Phone           VARCHAR(50)     NULL,   -- formatos inconsistentes (+51..., (01)..., sin código país)
    City            NVARCHAR(100)   NULL,
    Country         NVARCHAR(100)   NULL,   -- "Peru" vs "PE" vs "perú" vs NULL
    Segment         VARCHAR(20)     NULL,   -- 'Regular','VIP','premium','Vip' -> sin CHECK
    SignupDate      DATE            NULL,
    CreatedAt       DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
    UpdatedAt       DATETIME2       NULL     -- se actualiza si cambia de segmento, etc.
);

-- =====================================================================
-- 2. dbo.Products
-- =====================================================================
CREATE TABLE dbo.Products (
    ProductID       INT IDENTITY(1,1) PRIMARY KEY,
    SKU             VARCHAR(50)     NULL,   -- sin UNIQUE: pueden repetirse por error de carga
    ProductName     NVARCHAR(300)   NULL,
    Category        NVARCHAR(100)   NULL,   -- 'Electronica' vs 'Electrónica' vs 'ELECTRONICA'
    Description     NVARCHAR(MAX)   NULL,   -- texto libre, insumo para RAG (Nivel 5)
    UnitPrice       DECIMAL(10,2)   NULL,   -- pueden aparecer negativos o NULL (error de carga)
    Status          VARCHAR(20)     NULL,   -- 'Active','active','Discontinued','DISC' -> sin CHECK
    CreatedAt       DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
    UpdatedAt       DATETIME2       NULL
);

-- =====================================================================
-- 3. dbo.Orders
-- =====================================================================
CREATE TABLE dbo.Orders (
    OrderID         INT IDENTITY(1,1) PRIMARY KEY,
    CustomerID      INT             NULL,   -- FK deshabilitada abajo -> puede haber huérfanos
    OrderDate       DATETIME2       NULL,
    Channel         VARCHAR(20)     NULL,   -- 'web','App','TIENDA','tienda_fisica' -> sin CHECK
    Status          VARCHAR(20)     NULL,   -- 'Pending','Completed','cancelled','CANCELLED'
    TotalAmount     DECIMAL(12,2)   NULL,   -- no siempre cuadra con SUM(OrderItems)
    CreatedAt       DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
    UpdatedAt       DATETIME2       NULL,
    CONSTRAINT FK_Orders_Customers FOREIGN KEY (CustomerID)
        REFERENCES dbo.Customers(CustomerID)
);

-- =====================================================================
-- 4. dbo.OrderItems
-- =====================================================================
CREATE TABLE dbo.OrderItems (
    OrderItemID     INT IDENTITY(1,1) PRIMARY KEY,
    OrderID         INT             NULL,   -- FK deshabilitada abajo -> puede haber huérfanos
    ProductID       INT             NULL,   -- FK deshabilitada abajo -> puede referenciar SKUs ya eliminados
    Quantity        INT             NULL,   -- pueden aparecer 0 o negativos (error de picking/devolución mal registrada)
    UnitPrice       DECIMAL(10,2)   NULL,   -- precio al momento de la orden (puede diferir del Products.UnitPrice actual)
    CreatedAt       DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
    CONSTRAINT FK_OrderItems_Orders FOREIGN KEY (OrderID)
        REFERENCES dbo.Orders(OrderID),
    CONSTRAINT FK_OrderItems_Products FOREIGN KEY (ProductID)
        REFERENCES dbo.Products(ProductID)
);

-- =====================================================================
-- 5. dbo.Payments
-- =====================================================================
CREATE TABLE dbo.Payments (
    PaymentID       INT IDENTITY(1,1) PRIMARY KEY,
    OrderID         INT             NULL,   -- FK deshabilitada abajo -> puede haber huérfanos
    PaymentMethod   VARCHAR(30)     NULL,   -- 'Credit Card','credit_card','PayPal','Efectivo'
    Amount          DECIMAL(12,2)   NULL,
    Status          VARCHAR(20)     NULL,   -- 'Approved','Pending','Failed','Refunded'
    PaymentDate     DATETIME2       NULL,
    CreatedAt       DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
    UpdatedAt       DATETIME2       NULL,   -- CLAVE: el pago cambia de estado después de creado el pedido
    CONSTRAINT FK_Payments_Orders FOREIGN KEY (OrderID)
        REFERENCES dbo.Orders(OrderID)
);

-- =====================================================================
-- 6. dbo.SupportTickets
-- =====================================================================
CREATE TABLE dbo.SupportTickets (
    TicketID        INT IDENTITY(1,1) PRIMARY KEY,
    CustomerID      INT             NULL,   -- FK deshabilitada abajo -> puede haber huérfanos
    Subject         NVARCHAR(300)   NULL,
    Body            NVARCHAR(MAX)   NULL,   -- texto libre no estructurado, insumo real de features/RAG
    Status          VARCHAR(20)     NULL,   -- 'Open','Closed','in_progress','CLOSED'
    Priority        VARCHAR(20)     NULL,   -- 'Low','High','urgente'
    CreatedAt       DATETIME2       NOT NULL DEFAULT SYSUTCDATETIME(),
    UpdatedAt       DATETIME2       NULL,
    CONSTRAINT FK_SupportTickets_Customers FOREIGN KEY (CustomerID)
        REFERENCES dbo.Customers(CustomerID)
);
GO

/* =====================================================================
   Deshabilitar validación de FKs (simula deuda técnica de sistema legacy)
   -----------------------------------------------------------------------
   Las relaciones quedan definidas en el catálogo (ChartDB y cualquier
   herramienta de introspección las va a detectar y dibujar en el ER),
   pero SQL Server ya no las valida en INSERT/UPDATE. Esto es lo que nos
   permite al generador de datos sintéticos crear registros huérfanos
   de forma intencional y realista.
   ===================================================================== */
ALTER TABLE dbo.Orders          NOCHECK CONSTRAINT ALL;
ALTER TABLE dbo.OrderItems      NOCHECK CONSTRAINT ALL;
ALTER TABLE dbo.Payments        NOCHECK CONSTRAINT ALL;
ALTER TABLE dbo.SupportTickets  NOCHECK CONSTRAINT ALL;
GO
