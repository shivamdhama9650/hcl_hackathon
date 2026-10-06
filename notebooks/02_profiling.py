# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # 02 Profiling Notebook
# MAGIC Thin wrapper executing src.profile on Bronze tables and displaying metrics.

# COMMAND ----------
import sys
from pathlib import Path

repo_root = Path(".").resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

dbutils.widgets.text("bronze_catalog", "medisync_catalog")
dbutils.widgets.text("bronze_schema", "bronze")

catalog = dbutils.widgets.get("bronze_catalog")
schema = dbutils.widgets.get("bronze_schema")

# COMMAND ----------
from src.config import get_config
from src.profile import profile_dataset, format_profiling_markdown

config = get_config()

# Load Bronze Delta tables as pandas DataFrames for profiling
entities = {
    "patients": spark.table(f"{catalog}.{schema}.bronze_patients").toPandas(),
    "encounters": spark.table(f"{catalog}.{schema}.bronze_encounters").toPandas(),
    "lab_results": spark.table(f"{catalog}.{schema}.bronze_lab_results").toPandas(),
    "claims": spark.table(f"{catalog}.{schema}.bronze_claims").toPandas(),
}

df_hosp = spark.table(f"{catalog}.governance.hospitals").toPandas()
valid_hospitals = set(df_hosp["hospital_id"].dropna().astype(str))

profile_report = profile_dataset(entities, config.business_keys, valid_hospital_ids=valid_hospitals)
markdown_summary = format_profiling_markdown(profile_report, "Databricks Bronze Data Quality Profiling")

# COMMAND ----------
displayHTML(f"<div style='font-family:sans-serif;'>{markdown_summary.replace('\n', '<br>')}</div>")
