"""
load_via_duckdb.py
===================
Carga los CSVs generados por data_generator.py a Azure SQL Database usando
la extension comunitaria `mssql` de DuckDB (protocolo TDS nativo, sin driver
ODBC instalado a nivel de sistema).

NOTA: esta extension es EXPERIMENTAL y mantenida por la comunidad (no es
parte del core de DuckDB). Es una alternativa a data_generator.py --load
(que usa pymssql, mas estable). Si este script te da problemas raros,
vuelve a data_generator.py sin perder mas tiempo aqui -- esto es solo el
paso de carga de datos semilla, no es parte de lo que se evalua en el reto.

Por que conexion en memoria (sin archivo .duckdb):
    Si usas duckdb.connect("algo.duckdb"), el ATTACH y el secret pueden
    quedar persistidos en ese archivo en disco -- incluyendo, potencialmente,
    tus credenciales. Con conexion en memoria, todo vive solo mientras el
    proceso de Python esta corriendo y desaparece al terminar.

Requisitos:
    pip install duckdb polars python-dotenv

Configuracion de conexion (.env junto a este script, o Colab Secrets):
    AZURE_SQL_SERVER=tu-servidor.database.windows.net
    AZURE_SQL_DATABASE=tu-base
    AZURE_SQL_USER=tu-usuario
    AZURE_SQL_PASSWORD=tu-password

Uso:
    python load_via_duckdb.py
"""

import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

CSV_DIR = Path(__file__).resolve().parent.parent / "output" / "csv"

# Orden logico de carga (no es obligatorio por el NOCHECK CONSTRAINT, pero
# ayuda a leer el log y a razonar sobre dependencias si algo falla)
TABLES = [
    ("Customers", "customers.csv"),
    ("Products", "products.csv"),
    ("Orders", "orders.csv"),
    ("OrderItems", "order_items.csv"),
    ("Payments", "payments.csv"),
    ("SupportTickets", "support_tickets.csv"),
]


def build_connection() -> duckdb.DuckDBPyConnection:
    """Conexion DuckDB en memoria, con la extension mssql cargada y el
    secret de Azure SQL creado a partir de variables de entorno."""
    load_dotenv()

    required_env = ["AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_SQL_USER", "AZURE_SQL_PASSWORD"]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        print(f"Faltan variables de entorno: {missing}")
        print("Crea un .env junto a este script (ver docstring) o expórtalas antes de correr.")
        sys.exit(1)

    conn = duckdb.connect()  # :memory: -- nada se persiste a disco

    conn.execute("INSTALL mssql FROM community;")
    conn.execute("LOAD mssql;")

    # El secret vive solo en esta conexion en memoria, nunca toca disco
    conn.execute(
        """
        CREATE SECRET azure_secret (
            TYPE mssql,
            host $host,
            port 1433,
            database $database,
            user $user,
            password $password
        );
        """,
        {
            "host": os.environ["AZURE_SQL_SERVER"],
            "database": os.environ["AZURE_SQL_DATABASE"],
            "user": os.environ["AZURE_SQL_USER"],
            "password": os.environ["AZURE_SQL_PASSWORD"],
        },
    )

    conn.execute("ATTACH '' AS azure_db (TYPE mssql, SECRET azure_secret);")
    return conn


def load_table(conn: duckdb.DuckDBPyConnection, table_name: str, csv_filename: str) -> None:
    csv_path = CSV_DIR / csv_filename
    if not csv_path.exists():
        print(f"  -> {table_name}: no se encontro {csv_path}, se omite (corre data_generator.py --no-load primero)")
        return

    try:
        conn.execute("BEGIN;")
        # SET IDENTITY_INSERT y el INSERT deben compartir la misma conexion
        # TDS fisica -> por eso van dentro de la misma transaccion explicita
        conn.execute(f"SELECT mssql_exec('azure_db', 'SET IDENTITY_INSERT dbo.{table_name} ON');")
        conn.execute(
            f"""
            INSERT INTO azure_db.dbo.{table_name}
            SELECT * FROM read_csv('{csv_path.as_posix()}', header=true);
            """
        )
        conn.execute(f"SELECT mssql_exec('azure_db', 'SET IDENTITY_INSERT dbo.{table_name} OFF');")
        conn.execute("COMMIT;")
        count = conn.execute(f"SELECT COUNT(*) FROM read_csv('{csv_path.as_posix()}', header=true)").fetchone()[0]
        print(f"  -> {table_name}: {count} filas cargadas")
    except Exception as exc:
        conn.execute("ROLLBACK;")
        print(f"  -> {table_name}: FALLO -- {exc}")
        print("     (si esto persiste, usa data_generator.py --load con pymssql en su lugar)")


def main() -> None:
    print("Conectando a Azure SQL via DuckDB (mssql extension)...")
    conn = build_connection()

    print("Cargando tablas...")
    for table_name, csv_filename in TABLES:
        load_table(conn, table_name, csv_filename)

    conn.close()
    print("\nListo.")


if __name__ == "__main__":
    main()