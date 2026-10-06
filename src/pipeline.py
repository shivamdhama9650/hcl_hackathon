import argparse
import datetime
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Set
import pandas as pd

from src.audit import record_audit_run
from src.bronze import write_bronze_batch
from src.config import AppConfig, get_config, setup_logger
from src.gold import build_gold_layer
from src.ingest import ingest_batch_files, read_reference_data
from src.profile import format_profiling_markdown, profile_dataset
from src.silver import build_silver_layer, load_silver_table

logger = setup_logger(__name__)


def setup_reference_tables(config: AppConfig) -> Set[str]:
    config.warehouse_path.mkdir(parents=True, exist_ok=True)
    df_hospitals, df_user_access = read_reference_data(config)
    conn = sqlite3.connect(config.sqlite_db_path)
    try:
        df_hospitals.to_sql("reference_hospitals", conn, if_exists="replace", index=False)
        df_user_access.to_sql("reference_user_access", conn, if_exists="replace", index=False)
    finally:
        conn.close()

    valid_hospital_ids = set(df_hospitals["hospital_id"].dropna().astype(str))
    return valid_hospital_ids


def apply_sql_views(config: AppConfig) -> None:
    rls_sql_file = Path(__file__).resolve().parent.parent / "sql" / "rls_views.sql"
    if rls_sql_file.is_file():
        sql_content = rls_sql_file.read_text(encoding="utf-8")
        conn = sqlite3.connect(config.sqlite_db_path)
        try:
            conn.executescript(sql_content)
        finally:
            conn.close()


def run_batch(batch_id: str, config: Optional[AppConfig] = None) -> Dict[str, Any]:
    active_config = config or get_config()
    started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rows_read = 0

    logger.info("==================================================================")
    logger.info("Starting pipeline execution for batch: %s", batch_id)
    logger.info("==================================================================")

    try:
        # Reference loading
        valid_hospitals = setup_reference_tables(active_config)

        # Stage 2: Ingest
        batch_dfs = ingest_batch_files(active_config, batch_id)
        rows_read = sum(len(df) for df in batch_dfs.values())

        # Stage 3: Bronze writes
        write_bronze_batch(active_config, batch_dfs)

        # Stage 4: Profile Bronze
        bronze_profile = profile_dataset(
            batch_dfs,
            active_config.business_keys,
            valid_hospital_ids=valid_hospitals,
        )

        # Stage 5 & 6: Silver, Quarantine, Masking & Vault
        reconciliation_stats = build_silver_layer(
            active_config,
            batch_dfs,
            batch_id,
            valid_hospital_ids=valid_hospitals,
        )

        rows_loaded = sum(s["silver_loaded"] for s in reconciliation_stats.values())
        rows_quarantined = sum(s["quarantined"] for s in reconciliation_stats.values())
        rows_superseded = sum(s["superseded"] for s in reconciliation_stats.values())

        # Stage 7: Profile Silver
        silver_dfs = {
            "patients": load_silver_table(active_config, active_config.table_silver_patients),
            "encounters": load_silver_table(active_config, active_config.table_silver_encounters),
            "lab_results": load_silver_table(active_config, active_config.table_silver_lab_results),
            "claims": load_silver_table(active_config, active_config.table_silver_claims),
        }
        silver_profile = profile_dataset(
            silver_dfs,
            active_config.business_keys,
            valid_hospital_ids=valid_hospitals,
        )

        # Stage 8: Gold layer
        gold_tables = build_gold_layer(active_config)

        # Refresh RLS and helper views
        apply_sql_views(active_config)

        # Stage 9: Audit log
        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record_audit_run(
            config=active_config,
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            rows_read=rows_read,
            rows_loaded=rows_loaded,
            rows_quarantined=rows_quarantined,
            rows_superseded=rows_superseded,
            status="SUCCESS",
            error_message=None,
        )

        # Save profile comparison artifact
        reports_dir = active_config.warehouse_path / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"profile_report_{batch_id}.md"

        bronze_md = format_profiling_markdown(bronze_profile, f"Bronze Profiling Report ({batch_id})")
        silver_md = format_profiling_markdown(silver_profile, f"Silver Profiling Report ({batch_id})")
        full_report = f"{bronze_md}\n\n---\n\n{silver_md}"
        report_file.write_text(full_report, encoding="utf-8")

        logger.info(
            "Batch %s completed successfully: read=%d, loaded=%d, quarantined=%d, superseded=%d",
            batch_id,
            rows_read,
            rows_loaded,
            rows_quarantined,
            rows_superseded,
        )

        return {
            "batch_id": batch_id,
            "status": "SUCCESS",
            "rows_read": rows_read,
            "rows_loaded": rows_loaded,
            "rows_quarantined": rows_quarantined,
            "rows_superseded": rows_superseded,
            "bronze_profile": bronze_profile,
            "silver_profile": silver_profile,
            "reconciliation": reconciliation_stats,
        }

    except Exception as exc:
        finished_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record_audit_run(
            config=active_config,
            batch_id=batch_id,
            started_at=started_at,
            finished_at=finished_at,
            rows_read=rows_read,
            rows_loaded=0,
            rows_quarantined=0,
            rows_superseded=0,
            status="FAILED",
            error_message=str(exc),
        )
        logger.error("Pipeline run failed for batch %s: %s", batch_id, exc, exc_info=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="MediSync Health Network Governed Data Pipeline")
    parser.add_argument("--batch", type=str, required=True, help="Batch ID to process (e.g. batch_0, batch_1, batch_2)")
    parser.add_argument("--data-root", type=str, default=None, help="DATA_ROOT directory override")
    parser.add_argument("--warehouse", type=str, default=None, help="Warehouse directory override")
    parser.add_argument("--salt", type=str, default=None, help="Secret salt override")

    args = parser.parse_args()
    config = get_config(
        data_root_override=args.data_root,
        warehouse_override=args.warehouse,
        salt_override=args.salt,
    )

    batch_arg = args.batch.strip().lower()
    if batch_arg == "all":
        batches = ["batch_0", "batch_1", "batch_2"]
    else:
        batches = [batch_arg]

    for b in batches:
        run_batch(b, config)


if __name__ == "__main__":
    main()
