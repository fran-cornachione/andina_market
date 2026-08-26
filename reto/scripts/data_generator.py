"""
data_generator.py
==================
Genera datos sinteticos "sucios" (con errores realistas) para Andina Market
y opcionalmente los carga a Azure SQL Database.

Que hace:
    1. Genera las 6 tablas en memoria respetando relaciones logicas entre ellas
       (Customers -> Orders -> OrderItems -> Payments, Customers -> SupportTickets),
       inyectando errores de calidad de datos a proposito (ver 01_create_tables.sql
       para el detalle de por que cada error existe).
    2. Escribe cada tabla como CSV en seed-data/output/csv/ usando Polars.
    3. (Opcional) Carga cada CSV a Azure SQL Database via pyodbc con
       fast_executemany, en lotes.
    4. Imprime un resumen de cuantos registros "sucios" se generaron por tipo
       de error, util para documentar la seccion de calidad de datos del README.

Requisitos:
    pip install faker polars pyodbc python-dotenv
    Driver ODBC 18 para SQL Server instalado en el sistema:
    https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server

Configuracion de conexion (crea un archivo .env junto a este script, NO lo subas
al repo -- ya esta en .gitignore):
    AZURE_SQL_SERVER=tu-servidor.database.windows.net
    AZURE_SQL_DATABASE=tu-base
    AZURE_SQL_USER=tu-usuario
    AZURE_SQL_PASSWORD=tu-password

Uso:
    python data_generator.py                # genera CSVs y carga a Azure SQL
    python data_generator.py --no-load       # solo genera CSVs, no carga nada
    python data_generator.py --seed 123      # reproducible con otra semilla
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl
from dotenv import load_dotenv
from faker import Faker

# ---------------------------------------------------------------------------
# Configuracion general
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output" / "csv"

N_CUSTOMERS = 600
N_PRODUCTS = 180
N_ORDERS = 2500
N_SUPPORT_TICKETS = 350
ITEMS_PER_ORDER_RANGE = (1, 5)

# Probabilidades de errores realistas inyectados (documentados junto al DDL)
P_NULL_EMAIL = 0.05
P_NULL_PHONE = 0.10
P_NULL_COUNTRY = 0.04
P_DUPLICATE_EMAIL = 0.04
P_MESSY_CASE = 0.15            # variantes de casing/typos en campos categoricos libres
P_ORPHAN_FK = 0.03              # referencia a una fila que no existe (posible por NOCHECK CONSTRAINT)
P_NEGATIVE_PRICE = 0.02
P_NULL_PRICE = 0.02
P_ZERO_OR_NEG_QTY = 0.03
P_AMOUNT_MISMATCH = 0.08
P_ORDER_WITHOUT_PAYMENT = 0.06
P_DUPLICATE_PAYMENT = 0.03

COUNTRIES = {
    "Peru": ["Lima", "Arequipa", "Trujillo", "Cusco"],
    "Colombia": ["Bogota", "Medellin", "Cali", "Barranquilla"],
    "Mexico": ["Ciudad de Mexico", "Guadalajara", "Monterrey", "Puebla"],
    "Chile": ["Santiago", "Valparaiso", "Concepcion"],
    "Argentina": ["Buenos Aires", "Cordoba", "Rosario"],
}
# Variantes "sucias" del mismo pais real (codigo ISO, minusculas, espacios, etc.)
COUNTRY_DIRTY_VARIANTS = {
    "Peru": ["PE", "peru", "Peru "],
    "Colombia": ["CO", "colombia"],
    "Mexico": ["MX", "mexico", "Mexico "],
    "Chile": ["CL", "chile"],
    "Argentina": ["AR", "argentina"],
}

SEGMENTS_CLEAN = ["Regular", "VIP", "Premium"]
SEGMENTS_DIRTY = ["regular", "vip", "PREMIUM", "Vip", "premium "]

CHANNELS_CLEAN = ["Web", "App", "Tienda"]
CHANNELS_DIRTY = ["web", "WEB", "app", "APP", "tienda", "TIENDA", "tienda_fisica"]

ORDER_STATUS_CLEAN = ["Pending", "Completed", "Cancelled", "Shipped"]
ORDER_STATUS_DIRTY = ["pending", "PENDING", "completed", "cancelled ", "CANCELLED"]

PRODUCT_STATUS_CLEAN = ["Active", "Discontinued"]
PRODUCT_STATUS_DIRTY = ["active", "ACTIVE", "discontinued", "DISC"]

PAYMENT_METHODS_CLEAN = ["Credit Card", "Debit Card", "PayPal", "Cash"]
PAYMENT_METHODS_DIRTY = ["credit_card", "Credit card", "paypal", "PAYPAL", "efectivo", "CASH"]

PAYMENT_STATUS_CLEAN = ["Approved", "Pending", "Failed", "Refunded"]
PAYMENT_STATUS_DIRTY = ["approved", "APPROVED", "pending ", "failed"]

TICKET_STATUS_CLEAN = ["Open", "In Progress", "Closed"]
TICKET_STATUS_DIRTY = ["open", "OPEN", "in_progress", "closed", "CLOSED"]

TICKET_PRIORITY_CLEAN = ["Low", "Medium", "High"]
TICKET_PRIORITY_DIRTY = ["low", "high", "URGENTE", "urgente", "Alta"]

CATEGORIES = ["Electronica", "Hogar", "Moda", "Deportes", "Belleza", "Juguetes", "Libros"]
CATEGORIES_DIRTY_MAP = {
    "Electronica": ["electronica", "ELECTRONICA", "Electronica "],
    "Hogar": ["hogar", "HOGAR"],
    "Moda": ["moda ", "MODA"],
    "Deportes": ["deportes", "Deporte"],
    "Belleza": ["belleza", "BELLEZA"],
    "Juguetes": ["juguetes", "Juguete"],
    "Libros": ["libros", "LIBROS"],
}

SUBJECT_TEMPLATES = [
    "Problema con mi pedido",
    "Consulta sobre devolucion",
    "Producto llego danado",
    "Duda sobre metodo de pago",
    "Solicitud de factura",
    "Producto no coincide con la descripcion",
]

# Varios locales para diversidad de nombres latinoamericanos
fake = Faker(["es_MX", "es_CO", "es_ES", "es_AR", "es_CL"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def maybe(prob: float) -> bool:
    return random.random() < prob


def dirty_or_clean(clean_value: str, dirty_options: list[str], prob: float = P_MESSY_CASE) -> str:
    return random.choice(dirty_options) if maybe(prob) else clean_value


# ---------------------------------------------------------------------------
# Generadores por tabla
# ---------------------------------------------------------------------------
def generate_customers(n: int) -> list[dict]:
    rows = []
    seen_emails: list[str] = []
    signup_start = datetime(2020, 1, 1)
    signup_end = datetime(2026, 8, 1)

    for i in range(1, n + 1):
        name = fake.name()
        if maybe(0.05):
            name = f"  {name.upper()}  "  # espacios extra / mayusculas (error de captura)

        if seen_emails and maybe(P_DUPLICATE_EMAIL):
            email = random.choice(seen_emails)
            if maybe(0.5):
                email = email.upper()
        else:
            email = fake.email()
        seen_emails.append(email)
        if maybe(P_NULL_EMAIL):
            email = None

        phone_formats = [
            fake.phone_number(),
            f"+{random.randint(1, 99)} {fake.msisdn()[:9]}",
            fake.numerify("#########"),
        ]
        phone = random.choice(phone_formats) if not maybe(P_NULL_PHONE) else None

        country_clean = random.choice(list(COUNTRIES.keys()))
        city = random.choice(COUNTRIES[country_clean])
        country = dirty_or_clean(country_clean, COUNTRY_DIRTY_VARIANTS[country_clean], prob=0.12)
        if maybe(P_NULL_COUNTRY):
            country = None

        segment = dirty_or_clean(random.choice(SEGMENTS_CLEAN), SEGMENTS_DIRTY)
        if maybe(0.05):
            segment = None

        signup_date = fake.date_time_between(start_date=signup_start, end_date=signup_end)
        created_at = signup_date
        updated_at = created_at if maybe(0.7) else fake.date_time_between(start_date=created_at, end_date=signup_end)

        rows.append(
            {
                "CustomerID": i,
                "FullName": name,
                "Email": email,
                "Phone": phone,
                "City": city,
                "Country": country,
                "Segment": segment,
                "SignupDate": signup_date.date().isoformat(),
                "CreatedAt": created_at.isoformat(sep=" "),
                "UpdatedAt": updated_at.isoformat(sep=" ") if updated_at else None,
            }
        )
    return rows


def generate_products(n: int) -> list[dict]:
    rows = []
    skus_used: list[str] = []

    for i in range(1, n + 1):
        category = random.choice(CATEGORIES)
        category_val = dirty_or_clean(category, CATEGORIES_DIRTY_MAP[category])
        name = f"{fake.word().capitalize()} {category} {fake.word().capitalize()}"

        sku_clean = f"SKU-{category[:3].upper()}-{i:05d}"
        sku = random.choice(skus_used) if skus_used and maybe(0.03) else sku_clean
        skus_used.append(sku_clean)

        price = round(random.uniform(5, 500), 2)
        if maybe(P_NEGATIVE_PRICE):
            price = -price
        if maybe(P_NULL_PRICE):
            price = None

        status = dirty_or_clean(random.choice(PRODUCT_STATUS_CLEAN), PRODUCT_STATUS_DIRTY)
        description = fake.paragraph(nb_sentences=4)

        created_at = fake.date_time_between(start_date="-3y", end_date="-6M")
        updated_at = created_at if maybe(0.6) else fake.date_time_between(start_date=created_at, end_date="now")

        rows.append(
            {
                "ProductID": i,
                "SKU": sku,
                "ProductName": name,
                "Category": category_val,
                "Description": description,
                "UnitPrice": price,
                "Status": status,
                "CreatedAt": created_at.isoformat(sep=" "),
                "UpdatedAt": updated_at.isoformat(sep=" "),
            }
        )
    return rows


def generate_orders(n: int, customer_ids: list[int]) -> list[dict]:
    rows = []
    max_customer_id = max(customer_ids)

    for i in range(1, n + 1):
        if maybe(P_ORPHAN_FK):
            customer_id = max_customer_id + random.randint(1, 500)  # no existe (huerfano intencional)
        else:
            customer_id = random.choice(customer_ids)

        order_date = fake.date_time_between(start_date="-2y", end_date="now")
        channel = dirty_or_clean(random.choice(CHANNELS_CLEAN), CHANNELS_DIRTY)
        status = dirty_or_clean(random.choice(ORDER_STATUS_CLEAN), ORDER_STATUS_DIRTY)
        updated_at = order_date if maybe(0.8) else fake.date_time_between(start_date=order_date, end_date="now")

        rows.append(
            {
                "OrderID": i,
                "CustomerID": customer_id,
                "OrderDate": order_date.isoformat(sep=" "),
                "Channel": channel,
                "Status": status,
                "TotalAmount": None,  # se calcula en generate_order_items()
                "CreatedAt": order_date.isoformat(sep=" "),
                "UpdatedAt": updated_at.isoformat(sep=" "),
                # campos internos usados solo para generacion, no se exportan a CSV:
                "_order_date_dt": order_date,
            }
        )
    return rows


def generate_order_items(orders: list[dict], products: list[dict]) -> list[dict]:
    rows = []
    order_totals = {o["OrderID"]: 0.0 for o in orders}
    order_ids = [o["OrderID"] for o in orders]
    max_order_id = max(order_ids)

    product_ids = [p["ProductID"] for p in products]
    max_product_id = max(product_ids)
    product_price_map = {p["ProductID"]: p["UnitPrice"] for p in products}

    item_id = 1
    for order in orders:
        n_items = random.randint(*ITEMS_PER_ORDER_RANGE)
        chosen_products = random.sample(product_ids, min(n_items, len(product_ids)))

        for product_id in chosen_products:
            if maybe(P_ORPHAN_FK):
                product_id_used = max_product_id + random.randint(1, 500)  # producto ya no existe
                unit_price = round(random.uniform(5, 500), 2)
            else:
                product_id_used = product_id
                base_price = product_price_map.get(product_id)
                if base_price is None:
                    base_price = round(random.uniform(5, 500), 2)
                # drift de precio historico: el precio al momento de la orden
                # no siempre coincide con el precio actual del catalogo
                unit_price = round(abs(base_price) * random.uniform(0.9, 1.1), 2)

            order_id_used = order["OrderID"]
            if maybe(P_ORPHAN_FK):
                order_id_used = max_order_id + random.randint(1, 500)  # orden ya no existe

            quantity = random.randint(1, 6)
            if maybe(P_ZERO_OR_NEG_QTY):
                quantity = random.choice([0, -1, -2])

            rows.append(
                {
                    "OrderItemID": item_id,
                    "OrderID": order_id_used,
                    "ProductID": product_id_used,
                    "Quantity": quantity,
                    "UnitPrice": unit_price,
                    "CreatedAt": order["CreatedAt"],
                }
            )
            if order_id_used in order_totals:
                order_totals[order_id_used] += quantity * unit_price
            item_id += 1

    # Backfill de Orders.TotalAmount, con ruido intencional (no siempre cuadra)
    for order in orders:
        real_total = round(order_totals.get(order["OrderID"], 0.0), 2)
        if maybe(P_AMOUNT_MISMATCH):
            order["TotalAmount"] = round(real_total * random.uniform(0.5, 1.5), 2)
        elif maybe(0.03):
            order["TotalAmount"] = None
        else:
            order["TotalAmount"] = real_total

    return rows


def generate_payments(orders: list[dict]) -> list[dict]:
    rows = []
    payment_id = 1
    order_ids = [o["OrderID"] for o in orders]
    max_order_id = max(order_ids)

    for order in orders:
        if maybe(P_ORDER_WITHOUT_PAYMENT):
            continue  # pedido sin pago registrado (pago pendiente / error de captura)

        n_payments = 2 if maybe(P_DUPLICATE_PAYMENT) else 1  # reintento de pago duplicado

        for _ in range(n_payments):
            order_id_used = order["OrderID"]
            if maybe(P_ORPHAN_FK):
                order_id_used = max_order_id + random.randint(1, 500)

            base_amount = order["TotalAmount"] if order["TotalAmount"] is not None else round(random.uniform(10, 500), 2)
            amount = base_amount
            if maybe(P_AMOUNT_MISMATCH) and base_amount:
                amount = round(base_amount * random.uniform(0.8, 1.2), 2)

            method = dirty_or_clean(random.choice(PAYMENT_METHODS_CLEAN), PAYMENT_METHODS_DIRTY)
            status = dirty_or_clean(random.choice(PAYMENT_STATUS_CLEAN), PAYMENT_STATUS_DIRTY)

            order_date_dt = order["_order_date_dt"]
            payment_date = order_date_dt + timedelta(minutes=random.randint(1, 120))
            created_at = payment_date
            # el pago cambia de estado DESPUES de creado el pedido -> UpdatedAt > CreatedAt
            updated_at = created_at + timedelta(hours=random.randint(1, 72)) if maybe(0.4) else created_at

            rows.append(
                {
                    "PaymentID": payment_id,
                    "OrderID": order_id_used,
                    "PaymentMethod": method,
                    "Amount": amount,
                    "Status": status,
                    "PaymentDate": payment_date.isoformat(sep=" "),
                    "CreatedAt": created_at.isoformat(sep=" "),
                    "UpdatedAt": updated_at.isoformat(sep=" "),
                }
            )
            payment_id += 1
    return rows


def generate_support_tickets(n: int, customer_ids: list[int]) -> list[dict]:
    rows = []
    max_customer_id = max(customer_ids)

    for i in range(1, n + 1):
        if maybe(P_ORPHAN_FK):
            customer_id = max_customer_id + random.randint(1, 500)
        else:
            customer_id = random.choice(customer_ids)

        subject = random.choice(SUBJECT_TEMPLATES)
        body = fake.paragraph(nb_sentences=6)
        status = dirty_or_clean(random.choice(TICKET_STATUS_CLEAN), TICKET_STATUS_DIRTY)
        priority = dirty_or_clean(random.choice(TICKET_PRIORITY_CLEAN), TICKET_PRIORITY_DIRTY)

        created_at = fake.date_time_between(start_date="-1y", end_date="now")
        updated_at = created_at if maybe(0.5) else fake.date_time_between(start_date=created_at, end_date="now")

        rows.append(
            {
                "TicketID": i,
                "CustomerID": customer_id,
                "Subject": subject,
                "Body": body,
                "Status": status,
                "Priority": priority,
                "CreatedAt": created_at.isoformat(sep=" "),
                "UpdatedAt": updated_at.isoformat(sep=" "),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Escritura de CSVs (Polars)
# ---------------------------------------------------------------------------
def write_csv(rows: list[dict], filename: str, drop_cols: list[str] | None = None) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clean_rows = rows
    if drop_cols:
        clean_rows = [{k: v for k, v in r.items() if k not in drop_cols} for r in rows]
    df = pl.DataFrame(clean_rows)
    path = OUTPUT_DIR / filename
    df.write_csv(path)
    print(f"  -> {filename}: {len(clean_rows)} filas")
    return path


# ---------------------------------------------------------------------------
# Carga a Azure SQL Database (pyodbc, fast_executemany, por lotes)
# ---------------------------------------------------------------------------
def load_to_azure_sql(table_name: str, csv_path: Path, batch_size: int = 1000) -> None:
    import pyodbc  # import diferido: solo se necesita si se va a cargar

    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={os.environ['AZURE_SQL_SERVER']};"
        f"DATABASE={os.environ['AZURE_SQL_DATABASE']};"
        f"UID={os.environ['AZURE_SQL_USER']};"
        f"PWD={os.environ['AZURE_SQL_PASSWORD']};"
        "Encrypt=yes;TrustServerCertificate=no;Connection Timeout=30;"
    )

    df = pl.read_csv(csv_path, try_parse_dates=True)
    records = df.to_dicts()
    if not records:
        print(f"  -> {table_name}: sin filas, se omite carga")
        return

    cols = list(records[0].keys())
    col_names = ", ".join(f"[{c}]" for c in cols)
    placeholders = ", ".join(["?"] * len(cols))
    insert_sql = f"INSERT INTO dbo.{table_name} ({col_names}) VALUES ({placeholders})"
    values = [tuple(r[c] for c in cols) for r in records]

    with pyodbc.connect(conn_str, autocommit=False) as conn:
        cursor = conn.cursor()
        cursor.fast_executemany = True
        try:
            cursor.execute(f"SET IDENTITY_INSERT dbo.{table_name} ON")
            for start in range(0, len(values), batch_size):
                cursor.executemany(insert_sql, values[start : start + batch_size])
            conn.commit()
        finally:
            cursor.execute(f"SET IDENTITY_INSERT dbo.{table_name} OFF")
            conn.commit()

    print(f"  -> {table_name}: {len(values)} filas cargadas")


# ---------------------------------------------------------------------------
# Resumen de calidad de datos (para copiar/pegar en tu README)
# ---------------------------------------------------------------------------
def print_summary(customers, products, orders, order_items, payments, tickets) -> None:
    customer_ids = {c["CustomerID"] for c in customers}
    order_ids = {o["OrderID"] for o in orders}

    n_null_email = sum(1 for c in customers if c["Email"] is None)
    n_null_phone = sum(1 for c in customers if c["Phone"] is None)
    n_dup_emails = len(customers) - len({c["Email"] for c in customers if c["Email"]})
    n_orphan_orders = sum(1 for o in orders if o["CustomerID"] not in customer_ids)
    n_negative_price = sum(1 for p in products if p["UnitPrice"] is not None and p["UnitPrice"] < 0)
    n_null_price = sum(1 for p in products if p["UnitPrice"] is None)
    n_orphan_items = sum(1 for oi in order_items if oi["OrderID"] not in order_ids)
    n_bad_qty = sum(1 for oi in order_items if oi["Quantity"] <= 0)
    n_orders_with_payment = len({p["OrderID"] for p in payments})
    n_orders_without_payment = len(orders) - n_orders_with_payment
    n_orphan_tickets = sum(1 for t in tickets if t["CustomerID"] not in customer_ids)

    print("\n=== Resumen de calidad de datos inyectada (copialo a tu README) ===")
    print(f"Customers totales:                {len(customers)}")
    print(f"  Email nulo:                     {n_null_email} ({n_null_email/len(customers):.1%})")
    print(f"  Email duplicado:                {n_dup_emails} ({n_dup_emails/len(customers):.1%})")
    print(f"  Phone nulo:                     {n_null_phone} ({n_null_phone/len(customers):.1%})")
    print(f"Products totales:                 {len(products)}")
    print(f"  UnitPrice negativo:             {n_negative_price}")
    print(f"  UnitPrice nulo:                 {n_null_price}")
    print(f"Orders totales:                   {len(orders)}")
    print(f"  CustomerID huerfano:            {n_orphan_orders} ({n_orphan_orders/len(orders):.1%})")
    print(f"  Sin Payment asociado:           {n_orders_without_payment} ({n_orders_without_payment/len(orders):.1%})")
    print(f"OrderItems totales:                {len(order_items)}")
    print(f"  OrderID huerfano:               {n_orphan_items}")
    print(f"  Quantity <= 0:                  {n_bad_qty}")
    print(f"SupportTickets totales:           {len(tickets)}")
    print(f"  CustomerID huerfano:            {n_orphan_tickets}")
    print("=====================================================================\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Generador de datos sinteticos para Andina Market")
    parser.add_argument("--no-load", action="store_true", help="Solo generar CSVs, no cargar a Azure SQL")
    parser.add_argument("--seed", type=int, default=42, help="Semilla para reproducibilidad")
    args = parser.parse_args()

    random.seed(args.seed)
    Faker.seed(args.seed)
    load_dotenv()

    print("Generando datos sinteticos...")
    customers = generate_customers(N_CUSTOMERS)
    products = generate_products(N_PRODUCTS)
    orders = generate_orders(N_ORDERS, [c["CustomerID"] for c in customers])
    order_items = generate_order_items(orders, products)  # tambien backfillea Orders.TotalAmount
    payments = generate_payments(orders)
    tickets = generate_support_tickets(N_SUPPORT_TICKETS, [c["CustomerID"] for c in customers])

    print("\nEscribiendo CSVs...")
    files = {
        "Customers": write_csv(customers, "customers.csv"),
        "Products": write_csv(products, "products.csv"),
        "Orders": write_csv(orders, "orders.csv", drop_cols=["_order_date_dt"]),
        "OrderItems": write_csv(order_items, "order_items.csv"),
        "Payments": write_csv(payments, "payments.csv"),
        "SupportTickets": write_csv(tickets, "support_tickets.csv"),
    }

    print_summary(customers, products, orders, order_items, payments, tickets)

    if args.no_load:
        print("--no-load activo: CSVs generados, no se cargo nada a Azure SQL.")
        return

    required_env = ["AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_SQL_USER", "AZURE_SQL_PASSWORD"]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        print(f"Faltan variables de entorno para conectar a Azure SQL: {missing}")
        print("Crea un archivo .env (ver docstring de este script) o corre con --no-load.")
        sys.exit(1)

    print("Cargando a Azure SQL Database...")
    # El orden no es estrictamente necesario (las FKs estan en NOCHECK), pero se
    # mantiene el orden logico por legibilidad del log de carga.
    load_to_azure_sql("Customers", files["Customers"])
    load_to_azure_sql("Products", files["Products"])
    load_to_azure_sql("Orders", files["Orders"])
    load_to_azure_sql("OrderItems", files["OrderItems"])
    load_to_azure_sql("Payments", files["Payments"])
    load_to_azure_sql("SupportTickets", files["SupportTickets"])
    print("\nCarga completa.")


if __name__ == "__main__":
    main()