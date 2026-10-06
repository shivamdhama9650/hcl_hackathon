import datetime
import logging
import sqlite3
from typing import Dict
import numpy as np
import pandas as pd

from src.config import AppConfig, setup_logger

logger = setup_logger(__name__)


def build_hospital_daily_admissions(silver_encounters: pd.DataFrame) -> pd.DataFrame:
    if silver_encounters.empty:
        return pd.DataFrame(columns=["hospital_id", "admission_date", "admissions", "unique_patients"])

    df = silver_encounters.dropna(subset=["hospital_id", "admit_date"]).copy()
    grouped = (
        df.groupby(["hospital_id", "admit_date"], as_index=False)
        .agg(
            admissions=("encounter_id", "count"),
            unique_patients=("patient_id", "nunique"),
        )
        .rename(columns={"admit_date": "admission_date"})
        .sort_values(["hospital_id", "admission_date"])
    )
    return grouped


def build_readmission_30d(silver_encounters: pd.DataFrame) -> pd.DataFrame:
    if silver_encounters.empty:
        return pd.DataFrame(columns=["hospital_id", "discharge_month", "discharges", "readmissions_30d", "readmission_rate"])

    df = silver_encounters.dropna(subset=["hospital_id", "admit_date", "discharge_date"]).copy()
    if df.empty:
        return pd.DataFrame(columns=["hospital_id", "discharge_month", "discharges", "readmissions_30d", "readmission_rate"])

    df["admit_dt"] = pd.to_datetime(df["admit_date"], errors="coerce")
    df["discharge_dt"] = pd.to_datetime(df["discharge_date"], errors="coerce")
    df = df.dropna(subset=["admit_dt", "discharge_dt"]).copy()

    df["discharge_month"] = df["discharge_dt"].dt.strftime("%Y-%m")

    # Vectorized self-merge on patient_id to identify readmissions within 30 days
    idx_cols = ["encounter_id", "patient_id", "discharge_dt"]
    sub_cols = ["encounter_id", "patient_id", "admit_dt"]
    pairs = df[idx_cols].merge(df[sub_cols], on="patient_id", suffixes=("", "_sub"))
    valid_readmissions = pairs[
        (pairs["encounter_id"] != pairs["encounter_id_sub"])
        & (pairs["admit_dt"] >= pairs["discharge_dt"])
        & (pairs["admit_dt"] <= pairs["discharge_dt"] + pd.Timedelta(days=30))
    ]
    readmit_ids = set(valid_readmissions["encounter_id"])
    df["is_readmission_30d"] = df["encounter_id"].isin(readmit_ids).astype(int)

    grouped = (
        df.groupby(["hospital_id", "discharge_month"], as_index=False)
        .agg(
            discharges=("encounter_id", "count"),
            readmissions_30d=("is_readmission_30d", "sum"),
        )
    )
    grouped["readmission_rate"] = (grouped["readmissions_30d"] / grouped["discharges"]).round(4)
    return grouped.sort_values(["hospital_id", "discharge_month"])


def build_claims_summary(
    silver_claims: pd.DataFrame,
    silver_encounters: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "hospital_id",
        "claim_month",
        "total_claims",
        "total_claim_amount",
        "avg_claim_amount",
        "approved_claims",
        "pending_claims",
        "rejected_claims",
        "approved_amount",
    ]
    if silver_claims.empty or silver_encounters.empty:
        return pd.DataFrame(columns=columns)

    enc_hosp = silver_encounters[["encounter_id", "hospital_id"]].drop_duplicates()
    merged = silver_claims.merge(enc_hosp, on="encounter_id", how="inner")

    if merged.empty:
        return pd.DataFrame(columns=columns)

    merged["claim_dt"] = pd.to_datetime(merged["claim_date"], errors="coerce")
    merged["claim_month"] = merged["claim_dt"].dt.strftime("%Y-%m")
    merged = merged.dropna(subset=["claim_month", "hospital_id"]).copy()

    records = []
    for (hosp, cmonth), group in merged.groupby(["hospital_id", "claim_month"]):
        tot_claims = len(group)
        tot_amount = round(float(group["claim_amount"].sum()), 2)
        avg_amount = round(float(group["claim_amount"].mean()), 2)

        approved_count = int((group["claim_status"] == "Approved").sum())
        pending_count = int((group["claim_status"] == "Pending").sum())
        rejected_count = int((group["claim_status"] == "Rejected").sum())

        approved_amt = round(float(group[group["claim_status"] == "Approved"]["approved_amount"].dropna().sum()), 2)

        records.append({
            "hospital_id": hosp,
            "claim_month": cmonth,
            "total_claims": tot_claims,
            "total_claim_amount": tot_amount,
            "avg_claim_amount": avg_amount,
            "approved_claims": approved_count,
            "pending_claims": pending_count,
            "rejected_claims": rejected_count,
            "approved_amount": approved_amt,
        })

    result = pd.DataFrame(records)
    if result.empty:
        return pd.DataFrame(columns=columns)
    return result.sort_values(["hospital_id", "claim_month"])


def build_lab_abnormality(
    silver_labs: pd.DataFrame,
    silver_encounters: pd.DataFrame,
) -> pd.DataFrame:
    columns = ["hospital_id", "test_code", "test_name", "total_tests", "abnormal_tests", "abnormality_rate"]
    if silver_labs.empty or silver_encounters.empty:
        return pd.DataFrame(columns=columns)

    enc_hosp = silver_encounters[["encounter_id", "hospital_id"]].drop_duplicates()
    merged = silver_labs.merge(enc_hosp, on="encounter_id", how="inner")

    if merged.empty:
        return pd.DataFrame(columns=columns)

    grouped = (
        merged.groupby(["hospital_id", "test_code", "test_name"], as_index=False)
        .agg(
            total_tests=("lab_result_id", "count"),
            abnormal_tests=("lab_flag", lambda s: (s == "abnormal").sum()),
        )
    )
    grouped["abnormality_rate"] = (grouped["abnormal_tests"] / grouped["total_tests"]).round(4)
    return grouped.sort_values(["hospital_id", "test_code"])


def build_gold_layer(config: AppConfig) -> Dict[str, pd.DataFrame]:
    silver_encounters_path = config.silver_path / f"{config.table_silver_encounters}.parquet"
    silver_labs_path = config.silver_path / f"{config.table_silver_lab_results}.parquet"
    silver_claims_path = config.silver_path / f"{config.table_silver_claims}.parquet"

    silver_encounters = pd.read_parquet(silver_encounters_path) if silver_encounters_path.is_file() else pd.DataFrame()
    silver_labs = pd.read_parquet(silver_labs_path) if silver_labs_path.is_file() else pd.DataFrame()
    silver_claims = pd.read_parquet(silver_claims_path) if silver_claims_path.is_file() else pd.DataFrame()

    gold_daily_adm = build_hospital_daily_admissions(silver_encounters)
    gold_readmissions = build_readmission_30d(silver_encounters)
    gold_claims = build_claims_summary(silver_claims, silver_encounters)
    gold_labs = build_lab_abnormality(silver_labs, silver_encounters)

    gold_tables = {
        config.table_gold_daily_admissions: gold_daily_adm,
        config.table_gold_readmission_30d: gold_readmissions,
        config.table_gold_claims_summary: gold_claims,
        config.table_gold_lab_abnormality: gold_labs,
    }

    config.gold_path.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.sqlite_db_path)

    try:
        for table_name, df in gold_tables.items():
            pq_path = config.gold_path / f"{table_name}.parquet"
            df.to_parquet(pq_path, index=False, engine="pyarrow")
            df.to_sql(table_name, conn, if_exists="replace", index=False)
            logger.info("Gold table %s overwritten with %d rows", table_name, len(df))
    finally:
        conn.close()

    return gold_tables
