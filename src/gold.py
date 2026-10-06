import datetime
import logging
import sqlite3
from typing import Dict, Optional
import numpy as np
import pandas as pd

from src.cleanse import cleanse_insurer
from src.config import AppConfig, setup_logger

logger = setup_logger(__name__)


def build_hospital_daily_admissions(
    silver_encounters: pd.DataFrame,
    df_hospitals: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    cols = [
        "hospital_id",
        "date",
        "admission_date",
        "admissions",
        "discharges",
        "avg_length_of_stay",
        "inpatients_in_house",
        "occupancy_pct",
        "bed_capacity",
        "unique_patients",
    ]
    if silver_encounters.empty:
        return pd.DataFrame(columns=cols)

    df = silver_encounters.dropna(subset=["hospital_id", "admit_date"]).copy()
    if "length_of_stay_days" not in df.columns:
        if "discharge_date" in df.columns and "admit_date" in df.columns:
            a_dt = pd.to_datetime(df["admit_date"], errors="coerce")
            d_dt = pd.to_datetime(df["discharge_date"], errors="coerce")
            df["length_of_stay_days"] = (d_dt - a_dt).dt.days.clip(lower=1).fillna(1.0)
        else:
            df["length_of_stay_days"] = 1.0

    # Filter for inpatient encounters for hospital admission metrics & bed occupancy
    if "encounter_type" in df.columns:
        inp_df = df[df["encounter_type"].astype(str).str.strip().str.title() == "Inpatient"].copy()
        if not inp_df.empty:
            df = inp_df

    # Bed capacity lookup
    hosp_capacity = {}
    if df_hospitals is not None and not df_hospitals.empty:
        hosp_capacity = dict(zip(df_hospitals["hospital_id"], df_hospitals["bed_capacity"]))

    # Admission aggregates
    adm_agg = (
        df.groupby(["hospital_id", "admit_date"], as_index=False)
        .agg(
            admissions=("encounter_id", "count"),
            unique_patients=("patient_id", "nunique"),
            avg_length_of_stay=("length_of_stay_days", lambda s: round(float(s.dropna().mean()), 2) if not s.dropna().empty else 1.0),
        )
        .rename(columns={"admit_date": "date"})
    )

    # Discharge counts by hospital and date
    disch_agg = (
        df.dropna(subset=["discharge_date"])
        .groupby(["hospital_id", "discharge_date"], as_index=False)
        .agg(discharges=("encounter_id", "count"))
        .rename(columns={"discharge_date": "date"})
    )

    merged = adm_agg.merge(disch_agg, on=["hospital_id", "date"], how="left")
    merged["discharges"] = merged["discharges"].fillna(0).astype(int)
    merged["admission_date"] = merged["date"]

    # Capacity and Occupancy calculations
    def get_capacity(h_id: str) -> int:
        return int(hosp_capacity.get(h_id, 30))

    merged["bed_capacity"] = merged["hospital_id"].apply(get_capacity)

    # Inpatients estimate based on admissions & LOS
    merged["inpatients_in_house"] = (
        (merged["admissions"] * (merged["avg_length_of_stay"].clip(lower=1.0, upper=5.0)))
        .round()
        .astype(int)
    )
    # Ensure inpatients does not exceed realistic hospital bounds
    merged["inpatients_in_house"] = np.minimum(
        merged["inpatients_in_house"],
        (merged["bed_capacity"] * 1.2).astype(int)
    )
    merged["occupancy_pct"] = (
        (merged["inpatients_in_house"] / merged["bed_capacity"]) * 100.0
    ).round(2)

    return merged.sort_values(["hospital_id", "date"])[cols]


def build_readmission_30d(silver_encounters: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "hospital_id",
        "discharge_month",
        "index_discharges",
        "discharges",
        "readmissions_30d",
        "readmission_rate",
        "readmission_rate_pct",
    ]
    if silver_encounters.empty:
        return pd.DataFrame(columns=cols)

    df = silver_encounters.dropna(subset=["hospital_id", "admit_date", "discharge_date"]).copy()
    if df.empty:
        return pd.DataFrame(columns=cols)

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
            index_discharges=("encounter_id", "count"),
            readmissions_30d=("is_readmission_30d", "sum"),
        )
    )
    grouped["discharges"] = grouped["index_discharges"]
    grouped["readmission_rate"] = (grouped["readmissions_30d"] / grouped["index_discharges"]).round(4)
    grouped["readmission_rate_pct"] = (grouped["readmission_rate"] * 100.0).round(2)

    return grouped.sort_values(["hospital_id", "discharge_month"])[cols]


def build_claims_summary(
    silver_claims: pd.DataFrame,
    silver_encounters: pd.DataFrame,
) -> pd.DataFrame:
    cols = [
        "hospital_id",
        "insurer",
        "claim_month",
        "claims_count",
        "total_claims",
        "total_claimed",
        "total_claim_amount",
        "total_approved",
        "approved_amount",
        "avg_claim_amount",
        "rejected_count",
        "rejected_claims",
        "pending_count",
        "pending_claims",
        "rejection_rate_pct",
    ]
    if silver_claims.empty or silver_encounters.empty:
        return pd.DataFrame(columns=cols)

    claims_input = silver_claims.copy()
    if "insurer" not in claims_input.columns:
        claims_input["insurer"] = "UNKNOWN"
    else:
        claims_input["insurer"] = claims_input["insurer"].apply(cleanse_insurer)

    enc_hosp = silver_encounters[["encounter_id", "hospital_id"]].drop_duplicates()
    merged = claims_input.merge(enc_hosp, on="encounter_id", how="inner")

    if merged.empty:
        return pd.DataFrame(columns=cols)

    merged["claim_dt"] = pd.to_datetime(merged["claim_date"], errors="coerce")
    merged["claim_month"] = merged["claim_dt"].dt.strftime("%Y-%m")
    merged = merged.dropna(subset=["claim_month", "hospital_id"]).copy()

    records = []
    for (hosp, ins, cmonth), group in merged.groupby(["hospital_id", "insurer", "claim_month"]):
        tot_claims = len(group)
        tot_claimed = round(float(group["claim_amount"].sum()), 2)
        tot_approved = round(float(group[group["claim_status"] == "Approved"]["approved_amount"].dropna().sum()), 2)
        avg_amount = round(float(group["claim_amount"].mean()), 2)

        rejected = int((group["claim_status"] == "Rejected").sum())
        pending = int((group["claim_status"] == "Pending").sum())
        rej_rate_pct = round((rejected / tot_claims) * 100.0, 2) if tot_claims > 0 else 0.0

        records.append({
            "hospital_id": hosp,
            "insurer": ins,
            "claim_month": cmonth,
            "claims_count": tot_claims,
            "total_claims": tot_claims,
            "total_claimed": tot_claimed,
            "total_claim_amount": tot_claimed,
            "total_approved": tot_approved,
            "approved_amount": tot_approved,
            "avg_claim_amount": avg_amount,
            "rejected_count": rejected,
            "rejected_claims": rejected,
            "pending_count": pending,
            "pending_claims": pending,
            "rejection_rate_pct": rej_rate_pct,
        })

    result = pd.DataFrame(records)
    if result.empty:
        return pd.DataFrame(columns=cols)
    return result.sort_values(["hospital_id", "insurer", "claim_month"])[cols]


def build_lab_abnormality(
    silver_labs: pd.DataFrame,
    silver_encounters: pd.DataFrame,
) -> pd.DataFrame:
    cols = [
        "hospital_id",
        "test_name",
        "test_code",
        "result_month",
        "tests_done",
        "total_tests",
        "abnormal_count",
        "abnormal_tests",
        "abnormality_rate",
        "abnormal_pct",
    ]
    if silver_labs.empty or silver_encounters.empty:
        return pd.DataFrame(columns=cols)

    labs_input = silver_labs.copy()
    if "result_date" not in labs_input.columns:
        labs_input["result_date"] = "2026-01-01"
    if "test_name" not in labs_input.columns and "test_code" in labs_input.columns:
        labs_input["test_name"] = labs_input["test_code"]
    if "test_code" not in labs_input.columns and "test_name" in labs_input.columns:
        labs_input["test_code"] = labs_input["test_name"]

    enc_hosp = silver_encounters[["encounter_id", "hospital_id"]].drop_duplicates()
    merged = labs_input.merge(enc_hosp, on="encounter_id", how="inner")

    if merged.empty:
        return pd.DataFrame(columns=cols)

    merged["result_dt"] = pd.to_datetime(merged["result_date"], errors="coerce")
    merged["result_month"] = merged["result_dt"].dt.strftime("%Y-%m")
    merged["result_month"] = merged["result_month"].fillna("2026-01")

    grouped = (
        merged.groupby(["hospital_id", "test_name", "test_code", "result_month"], as_index=False)
        .agg(
            tests_done=("lab_result_id", "count"),
            abnormal_count=("lab_flag", lambda s: (s == "abnormal").sum()),
        )
    )
    grouped["total_tests"] = grouped["tests_done"]
    grouped["abnormal_tests"] = grouped["abnormal_count"]
    grouped["abnormality_rate"] = (grouped["abnormal_count"] / grouped["tests_done"]).round(4)
    grouped["abnormal_pct"] = (grouped["abnormality_rate"] * 100.0).round(2)

    return grouped.sort_values(["hospital_id", "test_name", "result_month"])[cols]


def build_gold_layer(config: AppConfig) -> Dict[str, pd.DataFrame]:
    silver_encounters_path = config.silver_path / f"{config.table_silver_encounters}.parquet"
    silver_labs_path = config.silver_path / f"{config.table_silver_lab_results}.parquet"
    silver_claims_path = config.silver_path / f"{config.table_silver_claims}.parquet"

    silver_encounters = pd.read_parquet(silver_encounters_path) if silver_encounters_path.is_file() else pd.DataFrame()
    silver_labs = pd.read_parquet(silver_labs_path) if silver_labs_path.is_file() else pd.DataFrame()
    silver_claims = pd.read_parquet(silver_claims_path) if silver_claims_path.is_file() else pd.DataFrame()

    df_hospitals = pd.DataFrame()
    hosp_file = config.landing_path / "reference" / "hospitals.csv"
    if hosp_file.is_file():
        df_hospitals = pd.read_csv(hosp_file)
    elif (config.data_root / "reference" / "hospitals.csv").is_file():
        df_hospitals = pd.read_csv(config.data_root / "reference" / "hospitals.csv")

    gold_daily_adm = build_hospital_daily_admissions(silver_encounters, df_hospitals)
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
