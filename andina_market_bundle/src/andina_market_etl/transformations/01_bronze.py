from pyspark import pipelines as dp
from pyspark.sql import functions as F

PATH = "/Volumes/andina_source/landing/files/csv"

# Lógica de ingesta reutilizable para archivos csv
def ingest_csv(file_name):
    return (
        spark.readStream
            .format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("cloudFiles.inferColumnTypes", "true") # Inferencia automática de tipos de datos
            .option("header", "true")
            .option("pathGlobFilter", file_name)
            .option("cloudFiles.schemaEvolutionMode", "addNewColumns") # Schema Evolution
            .option("rescuedDataColumn", "_rescued_data") # Columna para rescatar datos corruptos  
            .load(PATH)
            .withColumn("_ingested_at", F.current_timestamp()) # Columna con timestamp de ingesta
    )

@dp.table
def customers():
    return ingest_csv("customers.csv")

@dp.table
def orders():
    return ingest_csv("orders.csv")

@dp.table
def order_items():
    return ingest_csv("order_items.csv")

@dp.table
def payments():
    return ingest_csv("payments.csv")

@dp.table
def products():
    return ingest_csv("products.csv")

@dp.table
def support_tickets():
    return ingest_csv("support_tickets.csv")