# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # 03 Silver & Quarantine Notebook
# MAGIC Thin wrapper transforming Bronze batch into cleansed, masked Silver tables using sql/merge_silver.sql MERGE statements.

# COMMAND ----------
import sys
from pathlib import Path

repo_root = Path(".").resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

dbutils.widgets.text("batch_id", "batch_0")
dbutils.widgets.text("catalog", "medisync_catalog")

batch_id = dbutils.widgets.get("batch_id")
catalog = dbutils.widgets.get("catalog")

# COMMAND ----------
from src.config import get_config
from src.silver import build_silver_layer

config = get_config()

# Load Bronze data for current batch
bronze_dfs = {
    "patients": spark.table(f"{catalog}.bronze.bronze_patients").filter(f"batch_id = '{batch_id}'").toPandas(),
    "encounters": spark.table(f"{catalog}.bronze.bronze_encounters").filter(f"batch_id = '{batch_id}'").toPandas(),
    "lab_results": spark.table(f"{catalog}.bronze.bronze_lab_results").filter(f"batch_id = '{batch_id}'").toPandas(),
    "claims": spark.table(f"{catalog}.bronze.bronze_claims").filter(f"batch_id = '{batch_id}'").toPandas(),
}

df_hosp = spark.table(f"{catalog}.governance.hospitals").toPandas()
valid_hospitals = set(df_hosp["hospital_id"].dropna().astype(str))

# Execute silver cleansing, deduplication, masking and quarantine
reconciliation_stats = build_silver_layer(
    config=config,
    bronze_dfs=bronze_dfs,
    batch_id=batch_id,
    valid_hospital_ids=valid_hospitals,
)

# COMMAND ----------
# Read sql/merge_silver.sql and apply Delta MERGE INTO
sql_path = repo_root / "sql" / "merge_silver.sql"
if sql_path.is_file():
    merge_statements = sql_path.read_text(encoding="utf-8").split(";")
    for stmt in merge_statements:
        clean_stmt = stmt.strip()
        if clean_stmt:
            spark.sql(clean_stmt)

print("Reconciliation Stats:", reconciliation_stats)
