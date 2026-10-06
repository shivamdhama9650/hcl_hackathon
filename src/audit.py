import datetime
import logging
import sqlite3
from typing import Optional
import pandas as pd

from src.config import AppConfig, setup_logger

logger = setup_logger(__name__)


def record_audit_run(
    config: AppConfig,
    batch_id: str,
    started_at: str,
    finished_at: str,
    rows_read: int,
    rows_loaded: int,
    rows_quarantined: int,
    rows_superseded: int,
    status: str,
    error_message: Optional[str] = None,
) -> None:
    config.audit_path.mkdir(parents=True, exist_ok=True)
    audit_file = config.audit_path / "batch_audit.parquet"

    audit_entry = {
        "batch_id": batch_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "rows_read": rows_read,
        "rows_loaded": rows_loaded,
        "rows_quarantined": rows_quarantined,
        "rows_superseded": rows_superseded,
        "status": status,
        "error_message": error_message or "",
    }

    df_new = pd.DataFrame([audit_entry])

    if audit_file.is_file():
        existing_df = pd.read_parquet(audit_file, engine="pyarrow")
        combined = pd.concat([existing_df, df_new], ignore_index=True)
    else:
        combined = df_new

    combined.to_parquet(audit_file, index=False, engine="pyarrow")

    conn = sqlite3.connect(config.sqlite_db_path)
    try:
        combined.to_sql(config.table_audit, conn, if_exists="replace", index=False)
    finally:
        conn.close()

    logger.info("Audit run logged: batch=%s, status=%s, read=%d, loaded=%d", batch_id, status, rows_read, rows_loaded)


def get_audit_log(config: AppConfig) -> pd.DataFrame:
    audit_file = config.audit_path / "batch_audit.parquet"
    if audit_file.is_file():
        return pd.read_parquet(audit_file, engine="pyarrow")
    return pd.DataFrame()
