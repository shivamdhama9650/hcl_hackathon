import datetime
import hashlib
import logging
from pathlib import Path
from typing import Dict
import pandas as pd
import pytest

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
from src.config import AppConfig, get_config
from src.gold import (
    build_claims_summary,
    build_hospital_daily_admissions,
    build_lab_abnormality,
    build_readmission_30d,
)
from src.masking import (
    mask_date_of_birth,
    mask_email,
    mask_full_name,
    mask_national_id,
    mask_phone,
    tokenize_patient_id,
)
from src.pipeline import run_batch
from src.silver import (
    build_silver_layer,
    load_silver_table,
    process_patients_silver,
)


# =====================================================================
# 1. Cleansing Rules Tests
# =====================================================================

def test_parse_date_to_iso() -> None:
    assert parse_date_to_iso("2026-01-01") == "2026-01-01"
    assert parse_date_to_iso("13/03/2025") == "2025-03-13"
    assert parse_date_to_iso("18-Nov-2025") == "2025-11-18"
    assert parse_date_to_iso("2025-03-27 19:31:22") == "2025-03-27"
    assert parse_date_to_iso("invalid-date-string") is None
    assert parse_date_to_iso(None) is None


def test_cleanse_gender() -> None:
    assert cleanse_gender("Male") == "M"
    assert cleanse_gender("male") == "M"
    assert cleanse_gender("M") == "M"
    assert cleanse_gender("Female") == "F"
    assert cleanse_gender("female") == "F"
    assert cleanse_gender("F") == "F"
    assert cleanse_gender("Other") == "O"
    assert cleanse_gender("other") == "O"
    assert cleanse_gender(None) == "U"
    assert cleanse_gender("unknown_variant") == "U"


def test_cleanse_name() -> None:
    assert cleanse_name("  vikram   mehta  ") == "Vikram Mehta"
    assert cleanse_name("AMIT NAIK") == "Amit Naik"
    assert cleanse_name(None) is None
    assert cleanse_name("   ") is None


def test_cleanse_phone() -> None:
    assert cleanse_phone("+91-7589770678") == "917589770678"
    assert cleanse_phone("7126048509") == "7126048509"
    assert cleanse_phone(None) is None


def test_cleanse_email() -> None:
    assert cleanse_email("valid.user@example.com") == "valid.user@example.com"
    assert cleanse_email("USER@DOMAIN.ORG") == "user@domain.org"
    assert cleanse_email("invalid-email.example.com") is None
    assert cleanse_email("user name@example.com") is None
    assert cleanse_email(None) is None


def test_derived_columns() -> None:
    ref_date = datetime.date(2026, 1, 1)
    age = compute_patient_age("2000-01-01", ref_date)
    assert age == 26

    band = compute_age_band("2000-01-01", ref_date)
    assert band == "20-29"

    los = compute_length_of_stay("2026-01-01", "2026-01-05")
    assert los == 4
    assert compute_length_of_stay("2026-01-01", None) is None

    assert compute_lab_flag("5.2", 4.0, 5.6) == "normal"
    assert compute_lab_flag("9.8", 4.0, 5.6) == "abnormal"
    assert compute_lab_flag("pending", 4.0, 5.6) == "abnormal"

    assert standardize_claim_status("Approved ") == "Approved"
    assert standardize_claim_status("REJECTED") == "Rejected"
    assert standardize_claim_status("Pending") == "Pending"

    assert standardize_test_name("  creatinine  ") == "CREATININE"


# =====================================================================
# 2. Masking Rules Tests (including Salt Not Logged)
# =====================================================================

def test_masking_rules() -> None:
    assert mask_full_name("Rahul Rao") == "R***"
    assert mask_full_name("") == "***"

    assert mask_phone("9876543210") == "******3210"
    assert mask_phone("123") == "******123"

    assert mask_email("kunal.gowda83@example.com") == "k***@example.com"
    assert mask_email(None) is None

    assert mask_national_id("745923018779") == "********8779"
    assert mask_national_id(None) == "********"

    ref_date = datetime.date(2026, 1, 1)
    assert mask_date_of_birth("1979-05-16", ref_date) == "40-49"

    salt = "secret_medisync_salt_123"
    token = tokenize_patient_id("P001", salt)
    expected_token = hashlib.sha256((salt + "P001").encode("utf-8")).hexdigest()
    assert token == expected_token


def test_salt_not_logged(caplog: pytest.LogCaptureFixture) -> None:
    salt = "super_classified_salt_999"
    with caplog.at_level(logging.DEBUG):
        tokenize_patient_id("P001", salt)
        logger = logging.getLogger("src.test")
        logger.info("Executing tokenization of patient identifier")

    for record in caplog.records:
        assert salt not in record.message


# =====================================================================
# 3. Deduplication & Watermark Invariant Tests
# =====================================================================

def test_dedupe_within_batch_keeps_max_last_updated() -> None:
    salt = "test_salt"
    as_of = datetime.date(2026, 1, 1)
    raw_df = pd.DataFrame([
        {
            "patient_id": "P001",
            "full_name": "Older Record",
            "gender": "M",
            "date_of_birth": "1980-01-01",
            "phone": "9876543210",
            "email": "p1@example.com",
            "national_id": 111122223333,
            "city": "Pune",
            "primary_hospital_id": "H01",
            "last_updated": "2026-01-01 10:00:00",
        },
        {
            "patient_id": "P001",
            "full_name": "Newer Record",
            "gender": "M",
            "date_of_birth": "1980-01-01",
            "phone": "9876543210",
            "email": "p1@example.com",
            "national_id": 111122223333,
            "city": "Pune",
            "primary_hospital_id": "H01",
            "last_updated": "2026-01-01 12:00:00",
        },
    ])

    silver_res, vault_res, q_recs, loaded, superseded = process_patients_silver(
        df_raw=raw_df,
        silver_existing=pd.DataFrame(),
        valid_hospital_ids={"H01"},
        batch_id="test_b0",
        salt=salt,
        as_of_date=as_of,
    )

    assert len(silver_res) == 1
    assert loaded == 1
    assert superseded == 1
    assert silver_res.iloc[0]["last_updated"] == "2026-01-01 12:00:00"
    assert vault_res.iloc[0]["full_name"] == "Newer Record"


def test_watermark_skips_redelivered_rows() -> None:
    salt = "test_salt"
    as_of = datetime.date(2026, 1, 1)

    initial_silver = pd.DataFrame([{
        "patient_id": tokenize_patient_id("P001", salt),
        "original_patient_id": "P001",
        "full_name": "N***",
        "gender": "M",
        "age_band": "40-49",
        "patient_age": 46,
        "phone": "******3210",
        "email": "p***@example.com",
        "national_id": "********3333",
        "city": "Pune",
        "primary_hospital_id": "H01",
        "last_updated": "2026-01-01 12:00:00",
        "batch_id": "b0",
    }])

    redelivered_df = pd.DataFrame([{
        "patient_id": "P001",
        "full_name": "Newer Record",
        "gender": "M",
        "date_of_birth": "1980-01-01",
        "phone": "9876543210",
        "email": "p1@example.com",
        "national_id": 111122223333,
        "city": "Pune",
        "primary_hospital_id": "H01",
        "last_updated": "2026-01-01 12:00:00",
    }])

    silver_res, vault_res, q_recs, loaded, superseded = process_patients_silver(
        df_raw=redelivered_df,
        silver_existing=initial_silver,
        valid_hospital_ids={"H01"},
        batch_id="test_redelivery",
        salt=salt,
        as_of_date=as_of,
    )

    assert loaded == 0
    assert superseded == 1
    assert len(silver_res) == 1


# =====================================================================
# 4. Reconciliation Invariant on Synthetic Fixture
# =====================================================================

def test_reconciliation_invariant_holds(tmp_path: Path) -> None:
    cfg = AppConfig(
        data_root=tmp_path / "data",
        landing_path=tmp_path / "landing",
        warehouse_path=tmp_path / "warehouse",
        bronze_path=tmp_path / "warehouse" / "bronze",
        silver_path=tmp_path / "warehouse" / "silver",
        gold_path=tmp_path / "warehouse" / "gold",
        quarantine_path=tmp_path / "warehouse" / "quarantine",
        vault_path=tmp_path / "warehouse" / "vault",
        audit_path=tmp_path / "warehouse" / "audit",
        sqlite_db_path=tmp_path / "warehouse" / "medisync.db",
        salt="test_salt_reconcile",
        log_level="INFO",
    )

    raw_patients = pd.DataFrame([
        # Valid row 1
        {"patient_id": "P1", "full_name": "A", "gender": "M", "date_of_birth": "1990-01-01", "phone": "1234567890", "email": "a@ex.com", "national_id": 1, "city": "City", "primary_hospital_id": "H01", "last_updated": "2026-01-01 10:00:00"},
        # Duplicate row 1 (superseded)
        {"patient_id": "P1", "full_name": "A2", "gender": "M", "date_of_birth": "1990-01-01", "phone": "1234567890", "email": "a@ex.com", "national_id": 1, "city": "City", "primary_hospital_id": "H01", "last_updated": "2026-01-01 11:00:00"},
        # Bad date (quarantined)
        {"patient_id": "P2", "full_name": "B", "gender": "F", "date_of_birth": "not-a-date", "phone": "1234567890", "email": "b@ex.com", "national_id": 2, "city": "City", "primary_hospital_id": "H01", "last_updated": "2026-01-01 10:00:00"},
        # Orphan hospital (quarantined)
        {"patient_id": "P3", "full_name": "C", "gender": "M", "date_of_birth": "1990-01-01", "phone": "1234567890", "email": "c@ex.com", "national_id": 3, "city": "City", "primary_hospital_id": "H99", "last_updated": "2026-01-01 10:00:00"},
    ])

    bronze_dfs = {
        "patients": raw_patients,
        "encounters": pd.DataFrame(),
        "lab_results": pd.DataFrame(),
        "claims": pd.DataFrame(),
    }

    stats = build_silver_layer(
        config=cfg,
        bronze_dfs=bronze_dfs,
        batch_id="batch_fixture",
        valid_hospital_ids={"H01"},
    )

    pat_stats = stats["patients"]
    assert pat_stats["bronze_rows"] == 4
    assert pat_stats["silver_loaded"] == 1
    assert pat_stats["quarantined"] == 2
    assert pat_stats["superseded"] == 1
    assert pat_stats["bronze_rows"] == pat_stats["silver_loaded"] + pat_stats["quarantined"] + pat_stats["superseded"]


# =====================================================================
# 5. Gold Tables Structure & No PII Tests
# =====================================================================

def test_gold_table_grains_and_no_pii() -> None:
    encounters_df = pd.DataFrame([
        {
            "encounter_id": "E1",
            "patient_id": "hashed_p1",
            "hospital_id": "H01",
            "admit_date": "2026-01-01",
            "discharge_date": "2026-01-03",
        },
        {
            "encounter_id": "E2",
            "patient_id": "hashed_p1",
            "hospital_id": "H01",
            "admit_date": "2026-01-10",
            "discharge_date": "2026-01-12",
        },
    ])

    gold_adm = build_hospital_daily_admissions(encounters_df)
    assert not gold_adm.duplicated(subset=["hospital_id", "admission_date"]).any()
    assert "full_name" not in gold_adm.columns
    assert "phone" not in gold_adm.columns

    gold_readm = build_readmission_30d(encounters_df)
    assert not gold_readm.duplicated(subset=["hospital_id", "discharge_month"]).any()
    assert "patient_id" not in gold_readm.columns

    claims_df = pd.DataFrame([
        {
            "claim_id": "C1",
            "encounter_id": "E1",
            "claim_amount": 1000.0,
            "approved_amount": 900.0,
            "claim_status": "Approved",
            "claim_date": "2026-01-05",
        }
    ])
    gold_claims = build_claims_summary(claims_df, encounters_df)
    assert not gold_claims.duplicated(subset=["hospital_id", "claim_month"]).any()

    labs_df = pd.DataFrame([
        {
            "lab_result_id": "L1",
            "encounter_id": "E1",
            "test_code": "GLUCOSE",
            "test_name": "GLUCOSE",
            "lab_flag": "abnormal",
        }
    ])
    gold_labs = build_lab_abnormality(labs_df, encounters_df)
    assert not gold_labs.duplicated(subset=["hospital_id", "test_code"]).any()
    assert "full_name" not in gold_labs.columns


# =====================================================================
# 6. End-to-End Double-Run Idempotency Test
# =====================================================================

def test_double_run_idempotency() -> None:
    config = get_config()
    res1 = run_batch("batch_0", config)
    assert res1["status"] == "SUCCESS"

    silver_patients_1 = load_silver_table(config, config.table_silver_patients)
    silver_encounters_1 = load_silver_table(config, config.table_silver_encounters)

    res2 = run_batch("batch_0", config)
    assert res2["status"] == "SUCCESS"

    silver_patients_2 = load_silver_table(config, config.table_silver_patients)
    silver_encounters_2 = load_silver_table(config, config.table_silver_encounters)

    assert len(silver_patients_1) == len(silver_patients_2)
    assert len(silver_encounters_1) == len(silver_encounters_2)
    assert res2["rows_loaded"] == 0
