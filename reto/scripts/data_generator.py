"""
data_generator.py
==================
Genera datos sinteticos "sucios" (con errores realistas) para Andina Market.
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
OUTPUT_DIR = "/Volumes/andina_source/landing/files/csv"

N_CUSTOMERS = 600
N_PRODUCTS = 180
N_ORDERS = 2500
N_SUPPORT_TICKETS = 350
ITEMS_PER_ORDER_RANGE = (1, 5)

# Probabilidades de errores realistas inyectados
P_NULL_EMAIL = 0.05
P_NULL_PHONE = 0.10
P_NULL_COUNTRY = 0.04
P_DUPLICATE_EMAIL = 0.04
P_MESSY_CASE = 0.15
P_ORPHAN_FK = 0.03
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

COUNTRY_WEIGHTS = {
    "Mexico": 0.30,
    "Colombia": 0.25,
    "Peru": 0.20,
    "Argentina": 0.15,
    "Chile": 0.10,
}

COUNTRY_DIRTY_VARIANTS = {
    "Peru": ["PE", "peru", "Peru "],
    "Colombia": ["CO", "colombia"],
    "Mexico": ["MX", "mexico", "Mexico "],
    "Chile": ["CL", "chile"],
    "Argentina": ["AR", "argentina"],
}

SEGMENTS_CLEAN = ["Regular", "VIP", "Premium"]
SEGMENTS_WEIGHTS = [0.65, 0.25, 0.10]
SEGMENTS_DIRTY = ["regular", "vip", "PREMIUM", "Vip", "premium "]

CHANNELS_CLEAN = ["Web", "App", "Tienda"]
CHANNELS_WEIGHTS = [0.45, 0.32, 0.23]
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

REAL_PRODUCTS = {
    "Electronica": ["Smartphone Galaxy S23", "Audífonos Bluetooth Noise Cancelling", "Smart TV 55 QLED", "Laptop Pro 16", "Cargador Carga Rápida 65W", "Consola de Videojuegos Pro", "Monitor Gamer 27 144Hz"],
    "Hogar": ["Aspiradora Robot Wi-Fi", "Cafetera Espresso Automática", "Juego de Sartenes Antiadherentes", "Lámpara LED Inteligente", "Freidora de Aire 5L", "Edredón Plumas Matrimonial"],
    "Moda": ["Chaqueta de Cuero Sintético", "Zapatillas Urbanas Classic", "Jeans Slim Fit", "Sudadera con Capucha", "Reloj Análogo Minimalista", "Gafas de Sol Polarizadas"],
    "Deportes": ["Mat de Yoga Antideslizante", "Mancuernas Ajustables 20kg", "Botella Térmica 1L", "Bicicleta de Montaña R29", "Cinta de Correr Plegable"],
    "Belleza": ["Sérum Facial Ácido Hialurónico", "Secador de Pelo Iónico", "Crema Hidratante Noche", "Kit de Maquillaje Profesional", "Perfume Eau de Parfum 100ml"],
    "Juguetes": ["Set de Bloques para Construcción", "Juego de Mesa Estrategia", "Muñeca Articulada", "Coche a Control Remoto All-Road"],
    "Libros": ["Hábitos Atómicos", "Cien Años de Soledad", "El Poder del Ahora", "Clean Code", "Sapiens: De animales a dioses"]
}

SUBJECT_TEMPLATES = [
    "Problema con mi pedido",
    "Consulta sobre devolucion",
    "Producto llego danado",
    "Duda sobre metodo de pago",
    "Solicitud de factura",
    "Producto no coincide con la descripcion",
]

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
    signup_end = datetime(2025, 12, 31)

    for i in range(1, n + 1):
        name = fake.name()
        if maybe(0.05):
            name = f"  {name.upper()}  "

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

        country_clean = random.choices(
            list(COUNTRY_WEIGHTS.keys()), weights=list(COUNTRY_WEIGHTS.values()), k=1
        )[0]
        city = random.choice(COUNTRIES[country_clean])
        country = dirty_or_clean(country_clean, COUNTRY_DIRTY_VARIANTS[country_clean], prob=0.12)
        if maybe(P_NULL_COUNTRY):
            country = None

        segment_clean = random.choices(SEGMENTS_CLEAN, weights=SEGMENTS_WEIGHTS, k=1)[0]
        segment = dirty_or_clean(segment_clean, SEGMENTS_DIRTY)
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
                "_signup_dt": signup_date
            }
        )
    return rows


def generate_products(n: int) -> list[dict]:
    rows = []
    skus_used: list[str] = []

    for i in range(1, n + 1):
        category = random.choice(CATEGORIES)
        category_val = dirty_or_clean(category, CATEGORIES_DIRTY_MAP[category])
        
        base_name = random.choice(REAL_PRODUCTS[category])
        name = f"{base_name} - Mod. {i:03d}" if maybe(0.2) else base_name

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


def generate_orders(n: int, customers: list[dict]) -> list[dict]:
    rows = []
    customer_ids = [c["CustomerID"] for c in customers]
    max_customer_id = max(customer_ids)
    customer_map = {c["CustomerID"]: c["_signup_dt"] for c in customers}

    for i in range(1, n + 1):
        if maybe(P_ORPHAN_FK):
            customer_id = max_customer_id + random.randint(1, 500)
            signup_dt = datetime(2021, 1, 1)
        else:
            customer_id = random.choice(customer_ids)
            signup_dt = customer_map[customer_id]

        order_date = fake.date_time_between(start_date=signup_dt, end_date="now")
        channel_clean = random.choices(CHANNELS_CLEAN, weights=CHANNELS_WEIGHTS, k=1)[0]
        channel = dirty_or_clean(channel_clean, CHANNELS_DIRTY)
        status = dirty_or_clean(random.choice(ORDER_STATUS_CLEAN), ORDER_STATUS_DIRTY)
        updated_at = order_date if maybe(0.8) else fake.date_time_between(start_date=order_date, end_date="now")

        rows.append(
            {
                "OrderID": i,
                "CustomerID": customer_id,
                "OrderDate": order_date.isoformat(sep=" "),
                "Channel": channel,
                "Status": status,
                "TotalAmount": None,
                "CreatedAt": order_date.isoformat(sep=" "),
                "UpdatedAt": updated_at.isoformat(sep=" "),
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

    # Distribucion Pareto (Best Sellers)
    product_weights = [1.0 / ((idx + 1) ** 0.8) for idx in range(len(product_ids))]

    item_id = 1
    for order in orders:
        n_items = random.randint(*ITEMS_PER_ORDER_RANGE)
        chosen_products = random.choices(product_ids, weights=product_weights, k=n_items)
        chosen_products = list(set(chosen_products))

        for product_id in chosen_products:
            if maybe(P_ORPHAN_FK):
                product_id_used = max_product_id + random.randint(1, 500)
                unit_price = round(random.uniform(5, 500), 2)
            else:
                product_id_used = product_id
                base_price = product_price_map.get(product_id)
                if base_price is None:
                    base_price = round(random.uniform(5, 500), 2)
                unit_price = round(abs(base_price) * random.uniform(0.9, 1.1), 2)

            order_id_used = order["OrderID"]
            if maybe(P_ORPHAN_FK):
                order_id_used = max_order_id + random.randint(1, 500)

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
            continue

        n_payments = 2 if maybe(P_DUPLICATE_PAYMENT) else 1

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
        
        # Resolucion realista en e-commerce (1 a 4 dias)
        if status in ["Closed", "CLOSED", "closed"]:
            hours_to_resolve = random.choices(
                [random.randint(1, 12), random.randint(12, 48), random.randint(48, 96)],
                weights=[0.50, 0.35, 0.15],
                k=1
            )[0]
            updated_at = created_at + timedelta(hours=hours_to_resolve)
        else:
            updated_at = created_at + timedelta(hours=random.randint(1, 12))

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
    clean_rows = rows
    if drop_cols:
        clean_rows = [{k: v for k, v in r.items() if k not in drop_cols} for r in rows]
    df = pl.DataFrame(clean_rows)
    path = f"{OUTPUT_DIR}/{filename}"
    df.write_csv(path)
    print(f"  -> {filename}: {len(clean_rows)} filas")
    return path


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
    orders = generate_orders(N_ORDERS, customers)
    order_items = generate_order_items(orders, products)
    payments = generate_payments(orders)
    tickets = generate_support_tickets(N_SUPPORT_TICKETS, [c["CustomerID"] for c in customers])

    print("\nEscribiendo CSVs...")
    write_csv(customers, "customers.csv", drop_cols=["_signup_dt"])
    write_csv(products, "products.csv")
    write_csv(orders, "orders.csv", drop_cols=["_order_date_dt"])
    write_csv(order_items, "order_items.csv")
    write_csv(payments, "payments.csv")
    write_csv(tickets, "support_tickets.csv")

    print("\n¡CSVs regenerados exitosamente!")


if __name__ == "__main__":
    main()