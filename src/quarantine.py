import datetime
import json
import logging
import sqlite3
import uuid
from typing import Any, Dict, List
import pandas as pd

from src.config import AppConfig, setup_logger

logger = setup_logger(__name__)


def build_quarantine_record(
    entity: str,
    business_key_value: str,
    reason: str,
    batch_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    safe_payload = {}
    for k, v in payload.items():
        if pd.isna(v) if not isinstance(v, (list, dict)) else False:
            safe_payload[k] = None
        elif isinstance(v, (datetime.datetime, datetime.date, pd.Timestamp)):
            safe_payload[k] = v.isoformat()
        else:
            safe_payload[k] = v

    return {
        "quarantine_id": str(uuid.uuid4()),
        "entity": entity,
        "business_key": str(business_key_value) if business_key_value is not None else "",
        "reason": reason,
        "batch_id": batch_id,
        "record_payload": json.dumps(safe_payload, default=str),
        "quarantine_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def write_quarantine_records(config: AppConfig, records: List[Dict[str, Any]]) -> int:
    if not records:
        return 0

    config.quarantine_path.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)

    batch_id = records[0]["batch_id"]
    parquet_path = config.quarantine_path / f"quarantine_{batch_id}.parquet"
    df.to_parquet(parquet_path, index=False, engine="pyarrow")

    conn = sqlite3.connect(config.sqlite_db_path)
    try:
        df.to_sql(config.table_quarantine, conn, if_exists="append", index=False)
    finally:
        conn.close()

    logger.warning("Quarantined %d invalid records for batch %s", len(records), batch_id)
    return len(records)


def load_quarantine_records(config: AppConfig) -> pd.DataFrame:
    parquet_files = sorted(config.quarantine_path.glob("quarantine_*.parquet"))
    if not parquet_files:
        return pd.DataFrame()

    dfs = [pd.read_parquet(p, engine="pyarrow") for p in parquet_files]
    return pd.concat(dfs, ignore_index=True)
