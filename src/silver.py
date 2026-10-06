import datetime
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import pandas as pd

from src.cleanse import (
    cleanse_email,
    cleanse_gender,
    cleanse_name,
    cleanse_phone,
    compute_age_band,
    compute_lab_flag,
    compute_length_of_stay,
    compute_patient_age,
    parse_date_to_iso,
    standardize_claim_status,
    standardize_test_name,
)
from src.config import AppConfig, setup_logger
from src.masking import (
    mask_date_of_birth,
    mask_email,
    mask_full_name,
    mask_national_id,
    mask_phone,
    tokenize_patient_id,
)
from src.quarantine import build_quarantine_record, write_quarantine_records

logger = setup_logger(__name__)


def load_silver_table(config: AppConfig, table_name: str) -> pd.DataFrame:
    parquet_path = config.silver_path / f"{table_name}.parquet"
    if parquet_path.is_file():
        return pd.read_parquet(parquet_path, engine="pyarrow")
    return pd.DataFrame()


def save_silver_table(config: AppConfig, table_name: str, df: pd.DataFrame) -> None:
    if df.empty and len(df.columns) == 0:
        return

    config.warehouse_path.mkdir(parents=True, exist_ok=True)
    config.silver_path.mkdir(parents=True, exist_ok=True)
    parquet_path = config.silver_path / f"{table_name}.parquet"
    df.to_parquet(parquet_path, index=False, engine="pyarrow")

    conn = sqlite3.connect(config.sqlite_db_path)
    try:
        df.to_sql(table_name, conn, if_exists="replace", index=False)
    finally:
        conn.close()


def save_vault_records(config: AppConfig, vault_df: pd.DataFrame) -> None:
    if vault_df.empty:
        return

    config.vault_path.mkdir(parents=True, exist_ok=True)
    existing_vault_path = config.vault_path / "pii_vault.parquet"

    if existing_vault_path.is_file():
        existing = pd.read_parquet(existing_vault_path, engine="pyarrow")
        combined = pd.concat([existing, vault_df], ignore_index=True)
        combined = combined.drop_duplicates(subset=["patient_id_token"], keep="last")
    else:
        combined = vault_df

    combined.to_parquet(existing_vault_path, index=False, engine="pyarrow")

    conn = sqlite3.connect(config.sqlite_db_path)
    try:
        combined.to_sql(config.table_pii_vault, conn, if_exists="replace", index=False)
    finally:
        conn.close()


def process_patients_silver(
    df_raw: pd.DataFrame,
    silver_existing: pd.DataFrame,
    valid_hospital_ids: Set[str],
    batch_id: str,
    salt: str,
    as_of_date: datetime.date,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[Dict[str, Any]], int, int]:
    quarantine_records: List[Dict[str, Any]] = []
    bronze_count = len(df_raw)

    if bronze_count == 0:
        return silver_existing, pd.DataFrame(), [], 0, 0

    valid_candidates: List[Dict[str, Any]] = []

    for _, row in df_raw.iterrows():
        p_dict = row.to_dict()
        p_id = str(row.get("patient_id") or "").strip()

        if not p_id:
            quarantine_records.append(
                build_quarantine_record("patients", p_id, "NULL_BUSINESS_KEY", batch_id, p_dict)
            )
            continue

        raw_dob = row.get("date_of_birth")
        dob_iso = parse_date_to_iso(raw_dob)
        if dob_iso is None:
            quarantine_records.append(
                build_quarantine_record("patients", p_id, "BAD_DATE_FORMAT", batch_id, p_dict)
            )
            continue

        hosp_id = str(row.get("primary_hospital_id") or "").strip()
        if hosp_id and hosp_id not in valid_hospital_ids:
            quarantine_records.append(
                build_quarantine_record("patients", p_id, "ORPHAN_FK", batch_id, p_dict)
            )
            continue

        p_dict["parsed_dob"] = dob_iso
        valid_candidates.append(p_dict)

    df_valid = pd.DataFrame(valid_candidates)
    if df_valid.empty:
        superseded_count = 0
        silver_loaded_count = 0
        return silver_existing, pd.DataFrame(), quarantine_records, silver_loaded_count, superseded_count

    df_valid["last_updated_parsed"] = pd.to_datetime(df_valid["last_updated"], errors="coerce")
    before_dedupe = len(df_valid)
    df_valid = df_valid.sort_values("last_updated_parsed").groupby("patient_id", as_index=False).last()
    intra_batch_superseded = before_dedupe - len(df_valid)

    watermark_map: Dict[str, pd.Timestamp] = {}
    if not silver_existing.empty and "original_patient_id" in silver_existing.columns:
        silver_existing["last_updated_dt"] = pd.to_datetime(silver_existing["last_updated"], errors="coerce")
        watermark_map = dict(zip(silver_existing["original_patient_id"], silver_existing["last_updated_dt"]))

    rows_to_load: List[Dict[str, Any]] = []
    vault_rows: List[Dict[str, Any]] = []
    watermark_superseded = 0

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

    for _, row in df_valid.iterrows():
        p_id = row["patient_id"]
        incoming_ts = row["last_updated_parsed"]
        existing_ts = watermark_map.get(p_id)

        if existing_ts is not None and pd.notna(existing_ts) and incoming_ts <= existing_ts:
            watermark_superseded += 1
            continue

        cleaned_name = cleanse_name(row.get("full_name"))
        cleaned_phone = cleanse_phone(row.get("phone"))
        cleaned_email = cleanse_email(row.get("email"))
        cleaned_gender = cleanse_gender(row.get("gender"))
        dob_iso = row["parsed_dob"]

        age = compute_patient_age(dob_iso, as_of_date)
        age_band = compute_age_band(dob_iso, as_of_date)

        tokenized_id = tokenize_patient_id(p_id, salt)

        vault_rows.append({
            "patient_id_token": tokenized_id,
            "original_patient_id": p_id,
            "full_name": cleaned_name,
            "phone": cleaned_phone,
            "email": cleaned_email,
            "national_id": str(row.get("national_id")),
            "date_of_birth": dob_iso,
            "batch_id": batch_id,
            "created_at": now_iso,
        })

        rows_to_load.append({
            "patient_id": tokenized_id,
            "original_patient_id": p_id,
            "full_name": mask_full_name(cleaned_name),
            "gender": cleaned_gender,
            "age_band": age_band,
            "patient_age": age,
            "phone": mask_phone(cleaned_phone),
            "email": mask_email(cleaned_email),
            "national_id": mask_national_id(row.get("national_id")),
            "city": cleanse_name(row.get("city")),
            "primary_hospital_id": row.get("primary_hospital_id"),
            "last_updated": str(row.get("last_updated")),
            "batch_id": batch_id,
        })

    superseded_count = intra_batch_superseded + watermark_superseded
    silver_loaded_count = len(rows_to_load)

    df_vault = pd.DataFrame(vault_rows)

    if rows_to_load:
        df_new_silver = pd.DataFrame(rows_to_load)
        if silver_existing.empty:
            silver_updated = df_new_silver
        else:
            combined = pd.concat([silver_existing, df_new_silver], ignore_index=True)
            combined = combined.drop_duplicates(subset=["original_patient_id"], keep="last")
            silver_updated = combined
    else:
        silver_updated = silver_existing

    if "last_updated_dt" in silver_updated.columns:
        silver_updated = silver_updated.drop(columns=["last_updated_dt"])

    return silver_updated, df_vault, quarantine_records, silver_loaded_count, superseded_count


def process_encounters_silver(
    df_raw: pd.DataFrame,
    silver_existing: pd.DataFrame,
    valid_hospital_ids: Set[str],
    valid_patient_ids: Set[str],
    batch_id: str,
    salt: str,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], int, int]:
    quarantine_records: List[Dict[str, Any]] = []
    bronze_count = len(df_raw)

    if bronze_count == 0:
        return silver_existing, [], 0, 0

    valid_candidates: List[Dict[str, Any]] = []

    for _, row in df_raw.iterrows():
        e_dict = row.to_dict()
        e_id = str(row.get("encounter_id") or "").strip()

        if not e_id:
            quarantine_records.append(
                build_quarantine_record("encounters", e_id, "NULL_BUSINESS_KEY", batch_id, e_dict)
            )
            continue

        raw_admit = row.get("admit_date")
        admit_iso = parse_date_to_iso(raw_admit)
        if admit_iso is None:
            quarantine_records.append(
                build_quarantine_record("encounters", e_id, "BAD_DATE_FORMAT", batch_id, e_dict)
            )
            continue

        raw_discharge = row.get("discharge_date")
        discharge_iso: Optional[str] = None
        if raw_discharge is not None and pd.notna(raw_discharge) and str(raw_discharge).strip():
            discharge_iso = parse_date_to_iso(raw_discharge)
            if discharge_iso is None:
                quarantine_records.append(
                    build_quarantine_record("encounters", e_id, "BAD_DATE_FORMAT", batch_id, e_dict)
                )
                continue

        hosp_id = str(row.get("hospital_id") or "").strip()
        if hosp_id not in valid_hospital_ids:
            quarantine_records.append(
                build_quarantine_record("encounters", e_id, "ORPHAN_FK", batch_id, e_dict)
            )
            continue

        p_id = str(row.get("patient_id") or "").strip()
        if p_id not in valid_patient_ids:
            quarantine_records.append(
                build_quarantine_record("encounters", e_id, "ORPHAN_FK", batch_id, e_dict)
            )
            continue

        e_dict["admit_date_iso"] = admit_iso
        e_dict["discharge_date_iso"] = discharge_iso
        valid_candidates.append(e_dict)

    df_valid = pd.DataFrame(valid_candidates)
    if df_valid.empty:
        return silver_existing, quarantine_records, 0, 0

    df_valid["last_updated_parsed"] = pd.to_datetime(df_valid["last_updated"], errors="coerce")
    before_dedupe = len(df_valid)
    df_valid = df_valid.sort_values("last_updated_parsed").groupby("encounter_id", as_index=False).last()
    intra_batch_superseded = before_dedupe - len(df_valid)

    watermark_map: Dict[str, pd.Timestamp] = {}
    if not silver_existing.empty and "encounter_id" in silver_existing.columns:
        silver_existing["last_updated_dt"] = pd.to_datetime(silver_existing["last_updated"], errors="coerce")
        watermark_map = dict(zip(silver_existing["encounter_id"], silver_existing["last_updated_dt"]))

    rows_to_load: List[Dict[str, Any]] = []
    watermark_superseded = 0

    for _, row in df_valid.iterrows():
        e_id = row["encounter_id"]
        incoming_ts = row["last_updated_parsed"]
        existing_ts = watermark_map.get(e_id)

        if existing_ts is not None and pd.notna(existing_ts) and incoming_ts <= existing_ts:
            watermark_superseded += 1
            continue

        admit_iso = row["admit_date_iso"]
        discharge_iso = row["discharge_date_iso"]
        los_days = compute_length_of_stay(admit_iso, discharge_iso)

        p_id = str(row["patient_id"]).strip()
        tokenized_patient_id = tokenize_patient_id(p_id, salt)

        diag_code = row.get("primary_diagnosis_code")
        if not diag_code and isinstance(row.get("diagnosis"), dict):
            diag_code = row["diagnosis"].get("primary_code")

        rows_to_load.append({
            "encounter_id": e_id,
            "patient_id": tokenized_patient_id,
            "original_patient_id": p_id,
            "hospital_id": str(row["hospital_id"]).strip(),
            "department": str(row.get("department") or "").strip(),
            "encounter_type": str(row.get("encounter_type") or "").strip(),
            "admit_date": admit_iso,
            "discharge_date": discharge_iso,
            "length_of_stay_days": los_days,
            "primary_diagnosis_code": str(diag_code or "").strip(),
            "attending_doctor_id": str(row.get("attending_doctor_id") or "").strip(),
            "last_updated": str(row.get("last_updated")),
            "batch_id": batch_id,
        })

    superseded_count = intra_batch_superseded + watermark_superseded
    silver_loaded_count = len(rows_to_load)

    if rows_to_load:
        df_new_silver = pd.DataFrame(rows_to_load)
        if silver_existing.empty:
            silver_updated = df_new_silver
        else:
            combined = pd.concat([silver_existing, df_new_silver], ignore_index=True)
            combined = combined.drop_duplicates(subset=["encounter_id"], keep="last")
            silver_updated = combined
    else:
        silver_updated = silver_existing

    if "last_updated_dt" in silver_updated.columns:
        silver_updated = silver_updated.drop(columns=["last_updated_dt"])

    return silver_updated, quarantine_records, silver_loaded_count, superseded_count


def process_lab_results_silver(
    df_raw: pd.DataFrame,
    silver_existing: pd.DataFrame,
    valid_encounter_ids: Set[str],
    batch_id: str,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], int, int]:
    quarantine_records: List[Dict[str, Any]] = []
    bronze_count = len(df_raw)

    if bronze_count == 0:
        return silver_existing, [], 0, 0

    valid_candidates: List[Dict[str, Any]] = []

    for _, row in df_raw.iterrows():
        l_dict = row.to_dict()
        l_id = str(row.get("lab_result_id") or "").strip()

        if not l_id:
            quarantine_records.append(
                build_quarantine_record("lab_results", l_id, "NULL_BUSINESS_KEY", batch_id, l_dict)
            )
            continue

        raw_ts = row.get("result_timestamp")
        ts_iso = parse_date_to_iso(raw_ts)
        if ts_iso is None:
            quarantine_records.append(
                build_quarantine_record("lab_results", l_id, "BAD_DATE_FORMAT", batch_id, l_dict)
            )
            continue

        e_id = str(row.get("encounter_id") or "").strip()
        if e_id not in valid_encounter_ids:
            quarantine_records.append(
                build_quarantine_record("lab_results", l_id, "ORPHAN_FK", batch_id, l_dict)
            )
            continue

        l_dict["result_timestamp_iso"] = ts_iso
        valid_candidates.append(l_dict)

    df_valid = pd.DataFrame(valid_candidates)
    if df_valid.empty:
        return silver_existing, quarantine_records, 0, 0

    df_valid["last_updated_parsed"] = pd.to_datetime(df_valid["last_updated"], errors="coerce")
    before_dedupe = len(df_valid)
    df_valid = df_valid.sort_values("last_updated_parsed").groupby("lab_result_id", as_index=False).last()
    intra_batch_superseded = before_dedupe - len(df_valid)

    watermark_map: Dict[str, pd.Timestamp] = {}
    if not silver_existing.empty and "lab_result_id" in silver_existing.columns:
        silver_existing["last_updated_dt"] = pd.to_datetime(silver_existing["last_updated"], errors="coerce")
        watermark_map = dict(zip(silver_existing["lab_result_id"], silver_existing["last_updated_dt"]))

    rows_to_load: List[Dict[str, Any]] = []
    watermark_superseded = 0

    for _, row in df_valid.iterrows():
        l_id = row["lab_result_id"]
        incoming_ts = row["last_updated_parsed"]
        existing_ts = watermark_map.get(l_id)

        if existing_ts is not None and pd.notna(existing_ts) and incoming_ts <= existing_ts:
            watermark_superseded += 1
            continue

        ref_low = float(row["reference_low"]) if pd.notna(row.get("reference_low")) else None
        ref_high = float(row["reference_high"]) if pd.notna(row.get("reference_high")) else None
        lab_flag = compute_lab_flag(row.get("result_value"), ref_low, ref_high)
        clean_test = standardize_test_name(row.get("test_name"))

        rows_to_load.append({
            "lab_result_id": l_id,
            "encounter_id": str(row["encounter_id"]).strip(),
            "test_name": clean_test,
            "test_code": clean_test,
            "result_value": str(row.get("result_value") or "").strip(),
            "unit": str(row.get("unit") or "").strip(),
            "reference_low": ref_low,
            "reference_high": ref_high,
            "lab_flag": lab_flag,
            "result_timestamp": str(row["result_timestamp"]),
            "result_date": row["result_timestamp_iso"],
            "last_updated": str(row.get("last_updated")),
            "batch_id": batch_id,
        })

    superseded_count = intra_batch_superseded + watermark_superseded
    silver_loaded_count = len(rows_to_load)

    if rows_to_load:
        df_new_silver = pd.DataFrame(rows_to_load)
        if silver_existing.empty:
            silver_updated = df_new_silver
        else:
            combined = pd.concat([silver_existing, df_new_silver], ignore_index=True)
            combined = combined.drop_duplicates(subset=["lab_result_id"], keep="last")
            silver_updated = combined
    else:
        silver_updated = silver_existing

    if "last_updated_dt" in silver_updated.columns:
        silver_updated = silver_updated.drop(columns=["last_updated_dt"])

    return silver_updated, quarantine_records, silver_loaded_count, superseded_count


def process_claims_silver(
    df_raw: pd.DataFrame,
    silver_existing: pd.DataFrame,
    valid_encounter_ids: Set[str],
    batch_id: str,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], int, int]:
    quarantine_records: List[Dict[str, Any]] = []
    bronze_count = len(df_raw)

    if bronze_count == 0:
        return silver_existing, [], 0, 0

    valid_candidates: List[Dict[str, Any]] = []

    for _, row in df_raw.iterrows():
        c_dict = row.to_dict()
        c_id = str(row.get("claim_id") or "").strip()

        if not c_id:
            quarantine_records.append(
                build_quarantine_record("claims", c_id, "NULL_BUSINESS_KEY", batch_id, c_dict)
            )
            continue

        raw_cdate = row.get("claim_date")
        cdate_iso = parse_date_to_iso(raw_cdate)
        if cdate_iso is None:
            quarantine_records.append(
                build_quarantine_record("claims", c_id, "BAD_DATE_FORMAT", batch_id, c_dict)
            )
            continue

        e_id = str(row.get("encounter_id") or "").strip()
        if e_id not in valid_encounter_ids:
            quarantine_records.append(
                build_quarantine_record("claims", c_id, "ORPHAN_FK", batch_id, c_dict)
            )
            continue

        c_dict["claim_date_iso"] = cdate_iso
        valid_candidates.append(c_dict)

    df_valid = pd.DataFrame(valid_candidates)
    if df_valid.empty:
        return silver_existing, quarantine_records, 0, 0

    df_valid["last_updated_parsed"] = pd.to_datetime(df_valid["last_updated"], errors="coerce")
    before_dedupe = len(df_valid)
    df_valid = df_valid.sort_values("last_updated_parsed").groupby("claim_id", as_index=False).last()
    intra_batch_superseded = before_dedupe - len(df_valid)

    watermark_map: Dict[str, pd.Timestamp] = {}
    if not silver_existing.empty and "claim_id" in silver_existing.columns:
        silver_existing["last_updated_dt"] = pd.to_datetime(silver_existing["last_updated"], errors="coerce")
        watermark_map = dict(zip(silver_existing["claim_id"], silver_existing["last_updated_dt"]))

    rows_to_load: List[Dict[str, Any]] = []
    watermark_superseded = 0

    for _, row in df_valid.iterrows():
        c_id = row["claim_id"]
        incoming_ts = row["last_updated_parsed"]
        existing_ts = watermark_map.get(c_id)

        if existing_ts is not None and pd.notna(existing_ts) and incoming_ts <= existing_ts:
            watermark_superseded += 1
            continue

        c_status = standardize_claim_status(row.get("claim_status"))
        c_amount = float(row["claim_amount"]) if pd.notna(row.get("claim_amount")) else 0.0
        app_amount = float(row["approved_amount"]) if pd.notna(row.get("approved_amount")) else None

        rows_to_load.append({
            "claim_id": c_id,
            "encounter_id": str(row["encounter_id"]).strip(),
            "insurer": str(row.get("insurer") or "").strip().title(),
            "claim_amount": c_amount,
            "approved_amount": app_amount,
            "claim_status": c_status,
            "claim_date": row["claim_date_iso"],
            "last_updated": str(row.get("last_updated")),
            "batch_id": batch_id,
        })

    superseded_count = intra_batch_superseded + watermark_superseded
    silver_loaded_count = len(rows_to_load)

    if rows_to_load:
        df_new_silver = pd.DataFrame(rows_to_load)
        if silver_existing.empty:
            silver_updated = df_new_silver
        else:
            combined = pd.concat([silver_existing, df_new_silver], ignore_index=True)
            combined = combined.drop_duplicates(subset=["claim_id"], keep="last")
            silver_updated = combined
    else:
        silver_updated = silver_existing

    if "last_updated_dt" in silver_updated.columns:
        silver_updated = silver_updated.drop(columns=["last_updated_dt"])

    return silver_updated, quarantine_records, silver_loaded_count, superseded_count


def build_silver_layer(
    config: AppConfig,
    bronze_dfs: Dict[str, pd.DataFrame],
    batch_id: str,
    valid_hospital_ids: Set[str],
) -> Dict[str, Dict[str, int]]:
    config.warehouse_path.mkdir(parents=True, exist_ok=True)
    as_of_date = datetime.date.today()
    reconciliation_stats: Dict[str, Dict[str, int]] = {}

    silver_patients_existing = load_silver_table(config, config.table_silver_patients)
    silver_encounters_existing = load_silver_table(config, config.table_silver_encounters)
    silver_labs_existing = load_silver_table(config, config.table_silver_lab_results)
    silver_claims_existing = load_silver_table(config, config.table_silver_claims)

    all_quarantine: List[Dict[str, Any]] = []

    # 1. Patients
    raw_patients = bronze_dfs.get("patients", pd.DataFrame())
    silver_patients, df_vault, q_pat, p_loaded, p_superseded = process_patients_silver(
        df_raw=raw_patients,
        silver_existing=silver_patients_existing,
        valid_hospital_ids=valid_hospital_ids,
        batch_id=batch_id,
        salt=config.salt,
        as_of_date=as_of_date,
    )
    all_quarantine.extend(q_pat)
    save_silver_table(config, config.table_silver_patients, silver_patients)
    save_vault_records(config, df_vault)
    reconciliation_stats["patients"] = {
        "bronze_rows": len(raw_patients),
        "silver_loaded": p_loaded,
        "quarantined": len(q_pat),
        "superseded": p_superseded,
    }

    # Available valid patient keys (both existing Silver + currently processed valid original IDs)
    valid_patients: Set[str] = set()
    if not silver_patients.empty and "original_patient_id" in silver_patients.columns:
        valid_patients.update(silver_patients["original_patient_id"].dropna().astype(str))

    # 2. Encounters
    raw_encounters = bronze_dfs.get("encounters", pd.DataFrame())
    silver_encounters, q_enc, e_loaded, e_superseded = process_encounters_silver(
        df_raw=raw_encounters,
        silver_existing=silver_encounters_existing,
        valid_hospital_ids=valid_hospital_ids,
        valid_patient_ids=valid_patients,
        batch_id=batch_id,
        salt=config.salt,
    )
    all_quarantine.extend(q_enc)
    save_silver_table(config, config.table_silver_encounters, silver_encounters)
    reconciliation_stats["encounters"] = {
        "bronze_rows": len(raw_encounters),
        "silver_loaded": e_loaded,
        "quarantined": len(q_enc),
        "superseded": e_superseded,
    }

    # Available valid encounter keys
    valid_encounters: Set[str] = set()
    if not silver_encounters.empty and "encounter_id" in silver_encounters.columns:
        valid_encounters.update(silver_encounters["encounter_id"].dropna().astype(str))

    # 3. Lab Results
    raw_labs = bronze_dfs.get("lab_results", pd.DataFrame())
    silver_labs, q_labs, l_loaded, l_superseded = process_lab_results_silver(
        df_raw=raw_labs,
        silver_existing=silver_labs_existing,
        valid_encounter_ids=valid_encounters,
        batch_id=batch_id,
    )
    all_quarantine.extend(q_labs)
    save_silver_table(config, config.table_silver_lab_results, silver_labs)
    reconciliation_stats["lab_results"] = {
        "bronze_rows": len(raw_labs),
        "silver_loaded": l_loaded,
        "quarantined": len(q_labs),
        "superseded": l_superseded,
    }

    # 4. Claims
    raw_claims = bronze_dfs.get("claims", pd.DataFrame())
    silver_claims, q_claims, c_loaded, c_superseded = process_claims_silver(
        df_raw=raw_claims,
        silver_existing=silver_claims_existing,
        valid_encounter_ids=valid_encounters,
        batch_id=batch_id,
    )
    all_quarantine.extend(q_claims)
    save_silver_table(config, config.table_silver_claims, silver_claims)
    reconciliation_stats["claims"] = {
        "bronze_rows": len(raw_claims),
        "silver_loaded": c_loaded,
        "quarantined": len(q_claims),
        "superseded": c_superseded,
    }

    write_quarantine_records(config, all_quarantine)

    # Invariant assertion
    for entity, counts in reconciliation_stats.items():
        bronze_total = counts["bronze_rows"]
        accounted = counts["silver_loaded"] + counts["quarantined"] + counts["superseded"]
        if bronze_total != accounted:
            msg = (
                f"Reconciliation invariant failed for '{entity}' in batch {batch_id}: "
                f"bronze_rows ({bronze_total}) != silver_loaded ({counts['silver_loaded']}) + "
                f"quarantined ({counts['quarantined']}) + superseded ({counts['superseded']}) = {accounted}"
            )
            logger.error(msg)
            raise ValueError(msg)
        logger.info(
            "Reconciliation verified for %s: bronze=%d == loaded(%d) + quarantined(%d) + superseded(%d)",
            entity,
            bronze_total,
            counts["silver_loaded"],
            counts["quarantined"],
            counts["superseded"],
        )

    # Data Quality assertions
    for name, df in [
        ("patients", silver_patients),
        ("encounters", silver_encounters),
        ("lab_results", silver_labs),
        ("claims", silver_claims),
    ]:
        key = config.business_keys[name]
        if not df.empty and df[key].isna().any():
            raise ValueError(f"DQ assertion failed: NULL business key detected in silver_{name}")

    if not silver_encounters.empty:
        if (~silver_encounters["hospital_id"].isin(valid_hospital_ids)).any():
            raise ValueError("DQ assertion failed: Orphan hospital_id detected in silver_encounters")

    return reconciliation_stats
