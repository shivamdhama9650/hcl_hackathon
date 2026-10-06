import json
import logging
from pathlib import Path
from typing import Dict, Optional
import pandas as pd
import sqlite3

from src.config import AppConfig, setup_logger

logger = setup_logger(__name__)


def serialize_nested_fields(df: pd.DataFrame) -> pd.DataFrame:
    df_copy = df.copy()
    for col in df_copy.columns:
        if df_copy[col].apply(lambda x: isinstance(x, (dict, list))).any():
            df_copy[col] = df_copy[col].apply(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)
    return df_copy


def write_bronze_batch(config: AppConfig, batch_dfs: Dict[str, pd.DataFrame]) -> Dict[str, int]:
    config.bronze_path.mkdir(parents=True, exist_ok=True)
    config.warehouse_path.mkdir(parents=True, exist_ok=True)
    written_counts: Dict[str, int] = {}

    db_conn = sqlite3.connect(config.sqlite_db_path)

    try:
        for entity, df in batch_dfs.items():
            if df.empty:
                written_counts[entity] = 0
                continue

            entity_bronze_dir = config.bronze_path / entity
            entity_bronze_dir.mkdir(parents=True, exist_ok=True)

            batch_id = str(df["batch_id"].iloc[0])
            parquet_file = entity_bronze_dir / f"{entity}_{batch_id}.parquet"

            serialized_df = serialize_nested_fields(df)
            serialized_df.to_parquet(parquet_file, index=False, engine="pyarrow")

            table_name = f"bronze_{entity}"
            serialized_df.to_sql(table_name, db_conn, if_exists="append", index=False)

            written_counts[entity] = len(df)
            logger.info(
                "Bronze append for %s [%s]: %d rows written to %s and table %s",
                entity,
                batch_id,
                len(df),
                parquet_file,
                table_name,
            )
    finally:
        db_conn.close()

    return written_counts


def load_bronze_batch(config: AppConfig, entity: str, batch_id: str) -> pd.DataFrame:
    entity_bronze_dir = config.bronze_path / entity
    target_file = entity_bronze_dir / f"{entity}_{batch_id}.parquet"

    if not target_file.is_file():
        raise FileNotFoundError(f"Bronze file not found for entity {entity} batch {batch_id}: {target_file}")

    return pd.read_parquet(target_file, engine="pyarrow")


def load_all_bronze(config: AppConfig, entity: str) -> pd.DataFrame:
    entity_bronze_dir = config.bronze_path / entity
    if not entity_bronze_dir.is_dir():
        return pd.DataFrame()

    parquet_files = sorted(entity_bronze_dir.glob(f"{entity}_*.parquet"))
    if not parquet_files:
        return pd.DataFrame()

    dfs = [pd.read_parquet(p, engine="pyarrow") for p in parquet_files]
    return pd.concat(dfs, ignore_index=True)
