# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # 01 Bronze Ingestion Notebook
# MAGIC Thin wrapper importing src.ingest to load raw multi-format files from UC Volume into Delta Bronze tables.

# COMMAND ----------
import os
import sys
from pathlib import Path

# Add repo root to sys.path
repo_root = Path(".").resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

dbutils.widgets.text("batch_id", "batch_0")
dbutils.widgets.text("volume_path", "/Volumes/medisync_catalog/landing/source_data")
dbutils.widgets.text("bronze_catalog", "medisync_catalog")
dbutils.widgets.text("bronze_schema", "bronze")

batch_id = dbutils.widgets.get("batch_id")
volume_path = dbutils.widgets.get("volume_path")
catalog = dbutils.widgets.get("bronze_catalog")
schema = dbutils.widgets.get("bronze_schema")

# COMMAND ----------
from src.config import get_config
from src.ingest import ingest_batch_files, read_reference_data
from src.bronze import serialize_nested_fields

config = get_config(data_root_override=volume_path)

# 1. Ingest Reference Data
df_hospitals, df_user_access = read_reference_data(config)
spark.createDataFrame(df_hospitals).write.format("delta").mode("overwrite").saveAsTable(f"{catalog}.governance.hospitals")
spark.createDataFrame(df_user_access).write.format("delta").mode("overwrite").saveAsTable(f"{catalog}.governance.user_access")

# 2. Ingest Batch Files
batch_dfs = ingest_batch_files(config, batch_id)

for entity_name, df_raw in batch_dfs.items():
    if df_raw.empty:
        continue
    df_clean = serialize_nested_fields(df_raw)
    spark_df = spark.createDataFrame(df_clean)
    target_table = f"{catalog}.{schema}.bronze_{entity_name}"
    spark_df.write.format("delta").mode("append").saveAsTable(target_table)
    print(f"Appended {len(df_raw)} records to {target_table}")
