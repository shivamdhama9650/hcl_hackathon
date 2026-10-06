# Databricks notebook source
# COMMAND ----------
# MAGIC %md
# MAGIC # 04 Gold Layer Aggregations Notebook
# MAGIC Thin wrapper computing 4 business aggregate tables using src.gold and overwriting Delta gold_* tables.

# COMMAND ----------
import sys
from pathlib import Path

repo_root = Path(".").resolve()
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

dbutils.widgets.text("catalog", "medisync_catalog")
catalog = dbutils.widgets.get("catalog")

# COMMAND ----------
from src.config import get_config
from src.gold import build_gold_layer

config = get_config()
gold_tables = build_gold_layer(config)

for table_name, df_gold in gold_tables.items():
    spark_df = spark.createDataFrame(df_gold)
    target_table = f"{catalog}.gold.{table_name}"
    spark_df.write.format("delta").mode("overwrite").saveAsTable(target_table)
    print(f"Overwrote Gold table {target_table} with {len(df_gold)} records")
