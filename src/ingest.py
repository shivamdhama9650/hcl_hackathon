import datetime
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd

from src.config import AppConfig, resolve_batch_directory, setup_logger

logger = setup_logger(__name__)


def stage_to_landing(source_dir: Path, landing_base: Path, subfolder_name: str) -> Path:
    target_landing_dir = landing_base / subfolder_name
    target_landing_dir.mkdir(parents=True, exist_ok=True)

    for item in source_dir.iterdir():
        if item.is_file():
            dest_file = target_landing_dir / item.name
            shutil.copy2(item, dest_file)

    logger.info("Copied source files from %s to landing directory %s", source_dir, target_landing_dir)
    return target_landing_dir


def read_patients_csv(file_paths: List[Path], batch_id: str) -> pd.DataFrame:
    dfs: List[pd.DataFrame] = []
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for path in file_paths:
        df = pd.read_csv(path, dtype=str)
        df["batch_id"] = batch_id
        df["source_file"] = path.name
        df["ingest_timestamp"] = timestamp
        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"No patients CSV files found for batch {batch_id}")

    return pd.concat(dfs, ignore_index=True)


def read_encounters_jsonl(file_paths: List[Path], batch_id: str) -> pd.DataFrame:
    dfs: List[pd.DataFrame] = []
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for path in file_paths:
        df = pd.read_json(path, lines=True, dtype=False)
        if "diagnosis" in df.columns:
            def extract_diagnosis(diag_val: object) -> Optional[str]:
                if isinstance(diag_val, dict):
                    return diag_val.get("primary_code")
                return None

            df["primary_diagnosis_code"] = df["diagnosis"].apply(extract_diagnosis)

        df["batch_id"] = batch_id
        df["source_file"] = path.name
        df["ingest_timestamp"] = timestamp
        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"No encounters JSONL files found for batch {batch_id}")

    return pd.concat(dfs, ignore_index=True)


def read_lab_results_txt(file_paths: List[Path], batch_id: str) -> pd.DataFrame:
    dfs: List[pd.DataFrame] = []
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for path in file_paths:
        df = pd.read_csv(path, sep="|")
        df["batch_id"] = batch_id
        df["source_file"] = path.name
        df["ingest_timestamp"] = timestamp
        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"No lab results TXT files found for batch {batch_id}")

    return pd.concat(dfs, ignore_index=True)


def read_claims_xlsx(file_paths: List[Path], batch_id: str) -> pd.DataFrame:
    dfs: List[pd.DataFrame] = []
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for path in file_paths:
        df = pd.read_excel(path, sheet_name="claims")
        df["batch_id"] = batch_id
        df["source_file"] = path.name
        df["ingest_timestamp"] = timestamp
        dfs.append(df)

    if not dfs:
        raise FileNotFoundError(f"No claims XLSX files found for batch {batch_id}")

    return pd.concat(dfs, ignore_index=True)


def read_reference_data(config: AppConfig) -> Tuple[pd.DataFrame, pd.DataFrame]:
    ref_source_dir = config.data_root / "reference"
    if not ref_source_dir.is_dir():
        raise FileNotFoundError(f"Reference directory not found at {ref_source_dir}")

    landing_ref_dir = stage_to_landing(ref_source_dir, config.landing_path, "reference")

    hospitals_file = landing_ref_dir / "hospitals.csv"
    if not hospitals_file.is_file():
        raise FileNotFoundError(f"hospitals.csv missing in {landing_ref_dir}")
    df_hospitals = pd.read_csv(hospitals_file)

    user_access_file: Optional[Path] = None
    for candidate in ["user_access.json", "user_access_json.txt"]:
        p = landing_ref_dir / candidate
        if p.is_file():
            user_access_file = p
            break

    if user_access_file is None:
        raise FileNotFoundError(f"User access JSON file missing in {landing_ref_dir}")

    with open(user_access_file, "r", encoding="utf-8") as f:
        user_access_data = json.load(f)

    df_user_access = pd.DataFrame(user_access_data)
    return df_hospitals, df_user_access


def ingest_batch_files(config: AppConfig, batch_id: str) -> Dict[str, pd.DataFrame]:
    batch_dir = resolve_batch_directory(config.data_root, batch_id)
    landing_batch_dir = stage_to_landing(batch_dir, config.landing_path, batch_dir.name)

    patient_files = sorted(landing_batch_dir.glob("patients_*.csv"))
    encounter_files = sorted(
        [p for p in landing_batch_dir.iterdir() if p.name.startswith("encounters_") and (p.suffix in [".jsonl", ".txt"])]
    )
    lab_files = sorted(landing_batch_dir.glob("lab_results_*.txt"))
    claims_files = sorted(landing_batch_dir.glob("claims_*.xlsx"))

    logger.info(
        "Discovered batch files for %s: patients=%d, encounters=%d, labs=%d, claims=%d",
        batch_id,
        len(patient_files),
        len(encounter_files),
        len(lab_files),
        len(claims_files),
    )

    df_patients = read_patients_csv(patient_files, batch_id)
    df_encounters = read_encounters_jsonl(encounter_files, batch_id)
    df_labs = read_lab_results_txt(lab_files, batch_id)
    df_claims = read_claims_xlsx(claims_files, batch_id)

    return {
        "patients": df_patients,
        "encounters": df_encounters,
        "lab_results": df_labs,
        "claims": df_claims,
    }
