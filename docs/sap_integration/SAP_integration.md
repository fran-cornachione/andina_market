### Ingesta desde SAP On-Premise (Propuesta de Arquitectura)

![](/Workspace/Users/cornachofrance@gmail.com/andina_market/docs/sap_integration/SAP_architecture.png)

Para el escenario donde la fuente de datos proviene de un sistema **SAP On-Premise** (como SAP ECC o S/4HANA), la ingesta no se realiza consultando directamente la base de datos transaccional para no afectar su rendimiento.

Se plantea un flujo desacoplado e incremental de punta a punta:

1. **Extracción Incremental con Azure Data Factory (ADF):** 
   Se configura ADF con el conector **`SAP Table`** (vía *Self-hosted Integration Runtime*) utilizando filtros por marca de agua (ej. por fecha de modificación `UpdatedAt`) o CDC para extraer **únicamente los registros nuevos o actualizados** periódicamente.

2. **Landing Zone en ADLS Gen2:** 
   Data Factory deposita estos deltas/lotes incrementales en un contenedor de **Azure Data Lake Storage Gen2** como nuevos archivos (ej. `.csv` o `.parquet`).

3. **Ingesta con Auto Loader a Bronze (Databricks):** 
   El pipeline de Databricks usa **Auto Loader (`cloudFiles`)** para detectar automáticamente los nuevos archivos que ADF va dejando en ADLS Gen2 e ingestarlos de forma continua a las tablas de la capa **Bronze Delta Lake**.

4. A partir de este punto, se aplica la arquitectura medallion como en el resto del proyecto.