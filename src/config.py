import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    data_root: Path
    landing_path: Path
    warehouse_path: Path
    bronze_path: Path
    silver_path: Path
    gold_path: Path
    quarantine_path: Path
    vault_path: Path
    audit_path: Path
    sqlite_db_path: Path
    salt: str
    log_level: str

    table_bronze_patients: str = "bronze_patients"
    table_bronze_encounters: str = "bronze_encounters"
    table_bronze_lab_results: str = "bronze_lab_results"
    table_bronze_claims: str = "bronze_claims"

    table_silver_patients: str = "silver_patients"
    table_silver_encounters: str = "silver_encounters"
    table_silver_lab_results: str = "silver_lab_results"
    table_silver_claims: str = "silver_claims"

    table_pii_vault: str = "pii_vault"
    table_quarantine: str = "quarantine_records"
    table_audit: str = "batch_audit"

    table_gold_daily_admissions: str = "gold_hospital_daily_admissions"
    table_gold_readmission_30d: str = "gold_readmission_30d"
    table_gold_claims_summary: str = "gold_claims_summary"
    table_gold_lab_abnormality: str = "gold_lab_abnormality"

    business_keys: Dict[str, str] = None

    def __post_init__(self) -> None:
        if self.business_keys is None:
            object.__setattr__(
                self,
                "business_keys",
                {
                    "patients": "patient_id",
                    "encounters": "encounter_id",
                    "lab_results": "lab_result_id",
                    "claims": "claim_id",
                },
            )


def get_config(
    data_root_override: Optional[str] = None,
    warehouse_override: Optional[str] = None,
    salt_override: Optional[str] = None,
) -> AppConfig:
    raw_data_root = data_root_override or os.getenv("DATA_ROOT", "./MediaSync_Source_Data")
    data_root = Path(raw_data_root).resolve()

    raw_wh = warehouse_override or os.getenv("WAREHOUSE_PATH", "./warehouse")
    warehouse_path = Path(raw_wh).resolve()

    raw_landing = os.getenv("LANDING_PATH", "./landing")
    landing_path = Path(raw_landing).resolve()

    salt = salt_override or os.getenv("MEDISYNC_SALT")
    if not salt or not str(salt).strip():
        raise ValueError("MEDISYNC_SALT environment variable is required and must not be empty.")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    bronze_path = warehouse_path / "bronze"
    silver_path = warehouse_path / "silver"
    gold_path = warehouse_path / "gold"
    quarantine_path = warehouse_path / "quarantine"
    vault_path = warehouse_path / "vault"
    audit_path = warehouse_path / "audit"
    sqlite_db_path = warehouse_path / "medisync.db"

    return AppConfig(
        data_root=data_root,
        landing_path=landing_path,
        warehouse_path=warehouse_path,
        bronze_path=bronze_path,
        silver_path=silver_path,
        gold_path=gold_path,
        quarantine_path=quarantine_path,
        vault_path=vault_path,
        audit_path=audit_path,
        sqlite_db_path=sqlite_db_path,
        salt=salt,
        log_level=log_level,
    )


def resolve_batch_directory(data_root: Path, batch_id: str) -> Path:
    normalized = batch_id.strip().lower()
    exact_path = data_root / normalized
    if exact_path.is_dir():
        return exact_path

    for child in data_root.iterdir():
        if child.is_dir() and child.name.lower().startswith(normalized):
            return child

    raise FileNotFoundError(
        f"Unable to find directory matching batch '{batch_id}' under {data_root}"
    )


def setup_logger(name: str = "medisync", log_level: Optional[str] = None) -> logging.Logger:
    logger = logging.getLogger(name)
    level_str = log_level or os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
