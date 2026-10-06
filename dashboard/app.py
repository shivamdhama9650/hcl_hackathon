import datetime
import os
from pathlib import Path
import sys
from typing import Dict, List, Tuple
import pandas as pd
import streamlit as st

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from dashboard.charts import (
        create_avg_los_bar,
        create_claims_stacked_bar,
        create_lab_abnormal_bar,
        create_lab_heatmap,
        create_occupancy_bar,
        create_operations_admissions_line,
        create_readmission_rate_bar,
        create_readmission_trend_line,
        create_rejection_rate_bar,
    )
except ModuleNotFoundError:
    from charts import (  # type: ignore
        create_avg_los_bar,
        create_claims_stacked_bar,
        create_lab_abnormal_bar,
        create_lab_heatmap,
        create_occupancy_bar,
        create_operations_admissions_line,
        create_readmission_rate_bar,
        create_readmission_trend_line,
        create_rejection_rate_bar,
    )

from src.config import get_config

st.set_page_config(
    page_title="MediSync Health Network — Leadership Dashboard",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

PII_FORBIDDEN_KEYWORDS = ["full_name", "phone", "email", "national_id"]


def assert_no_pii(df: pd.DataFrame, table_name: str) -> None:
    for col in df.columns:
        col_lower = col.lower()
        for kw in PII_FORBIDDEN_KEYWORDS:
            if kw in col_lower:
                raise ValueError(
                    f"CRITICAL SECURITY VIOLATION: Forbidden PII field '{col}' discovered in Gold table '{table_name}'!"
                )


@st.cache_data
def load_gold_data() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    config = get_config()
    gold_dir = config.gold_path

    path_daily = gold_dir / f"{config.table_gold_daily_admissions}.parquet"
    path_readm = gold_dir / f"{config.table_gold_readmission_30d}.parquet"
    path_claims = gold_dir / f"{config.table_gold_claims_summary}.parquet"
    path_labs = gold_dir / f"{config.table_gold_lab_abnormality}.parquet"

    hosp_file = config.landing_path / "reference" / "hospitals.csv"
    if not hosp_file.is_file():
        hosp_file = config.data_root / "reference" / "hospitals.csv"

    if not hosp_file.is_file():
        st.error(f"Reference hospitals file not found at {hosp_file}")
        st.stop()

    df_hospitals = pd.read_csv(hosp_file)

    for path, name in [
        (path_daily, "gold_hospital_daily_admissions"),
        (path_readm, "gold_readmission_30d"),
        (path_claims, "gold_claims_summary"),
        (path_labs, "gold_lab_abnormality"),
    ]:
        if not path.is_file():
            st.error(f"Gold table Parquet file not found: {path}. Run pipeline batches first.")
            st.stop()

    df_daily = pd.read_parquet(path_daily)
    df_readm = pd.read_parquet(path_readm)
    df_claims = pd.read_parquet(path_claims)
    df_labs = pd.read_parquet(path_labs)

    # Security check: fail fast if PII detected
    for name, df in [
        ("gold_hospital_daily_admissions", df_daily),
        ("gold_readmission_30d", df_readm),
        ("gold_claims_summary", df_claims),
        ("gold_lab_abnormality", df_labs),
    ]:
        assert_no_pii(df, name)

    # Attach hospital names and regions
    hosp_map = dict(zip(df_hospitals["hospital_id"], df_hospitals["hospital_name"]))
    region_map = dict(zip(df_hospitals["hospital_id"], df_hospitals["region"]))

    for df in [df_daily, df_readm, df_claims, df_labs]:
        if "hospital_name" not in df.columns:
            df["hospital_name"] = df["hospital_id"].map(hosp_map)
        if "region" not in df.columns:
            df["region"] = df["hospital_id"].map(region_map)

    return df_daily, df_readm, df_claims, df_labs, df_hospitals


def main() -> None:
    df_daily, df_readm, df_claims, df_labs, df_hospitals = load_gold_data()

    st.title("MediSync Health Network — Leadership Dashboard")
    st.caption("Governed Multi-Hospital Analytics & Executive Performance Intelligence")

    # =========================================================================
    # SIDEBAR: Global Filters
    # =========================================================================
    st.sidebar.header("Global Network Filters")

    # Region Filter
    all_regions = ["All Regions"] + sorted(df_hospitals["region"].dropna().unique().tolist())
    selected_region = st.sidebar.selectbox("Geographic Region", all_regions, index=0)

    # Hospital Filter (filtered by selected region)
    available_hosps = df_hospitals.copy()
    if selected_region != "All Regions":
        available_hosps = available_hosps[available_hosps["region"] == selected_region]

    hosp_options = available_hosps["hospital_name"].tolist()
    selected_hospitals = st.sidebar.multiselect(
        "Hospital Facilities",
        options=hosp_options,
        default=hosp_options,
    )

    # Date Range Filter
    min_date = pd.to_datetime(df_daily["date"]).min().date()
    max_date = pd.to_datetime(df_daily["date"]).max().date()

    date_range = st.sidebar.date_input(
        "Date Range",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
    elif isinstance(date_range, (list, tuple)) and len(date_range) == 1:
        start_date = date_range[0]
        end_date = max_date
    else:
        start_date, end_date = min_date, max_date

    # Edge Case Guard: Empty Selection
    if not selected_hospitals:
        st.warning("⚠️ No hospitals selected in the filter. Please select at least one facility to display metrics.")
        st.stop()

    # Filter DataFrames
    selected_hosp_ids = set(df_hospitals[df_hospitals["hospital_name"].isin(selected_hospitals)]["hospital_id"])

    # 1. Filter Daily Admissions
    f_daily = df_daily[
        (df_daily["hospital_id"].isin(selected_hosp_ids))
        & (pd.to_datetime(df_daily["date"]).dt.date >= start_date)
        & (pd.to_datetime(df_daily["date"]).dt.date <= end_date)
    ].copy()

    # 2. Filter Readmissions
    start_m = start_date.strftime("%Y-%m")
    end_m = end_date.strftime("%Y-%m")
    f_readm = df_readm[
        (df_readm["hospital_id"].isin(selected_hosp_ids))
        & (df_readm["discharge_month"] >= start_m)
        & (df_readm["discharge_month"] <= end_m)
    ].copy()

    # 3. Filter Claims
    f_claims = df_claims[
        (df_claims["hospital_id"].isin(selected_hosp_ids))
        & (df_claims["claim_month"] >= start_m)
        & (df_claims["claim_month"] <= end_m)
    ].copy()

    # 4. Filter Labs
    f_labs = df_labs[
        (df_labs["hospital_id"].isin(selected_hosp_ids))
        & (df_labs["result_month"] >= start_m)
        & (df_labs["result_month"] <= end_m)
    ].copy()

    # =========================================================================
    # EXECUTIVE KPI ROW
    # =========================================================================
    tot_admissions = int(f_daily["admissions"].sum()) if not f_daily.empty else 0
    avg_occ = float(f_daily["occupancy_pct"].mean()) if not f_daily.empty else 0.0

    tot_disch = int(f_readm["index_discharges"].sum()) if not f_readm.empty else 0
    tot_readm = int(f_readm["readmissions_30d"].sum()) if not f_readm.empty else 0
    readm_rate = ((tot_readm / tot_disch) * 100.0) if tot_disch > 0 else 0.0

    tot_claimed = float(f_claims["total_claimed"].sum()) if not f_claims.empty else 0.0

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric("Total Admissions", f"{tot_admissions:,}")
    with kpi2:
        st.metric("Average Occupancy", f"{avg_occ:.1f}%")
    with kpi3:
        st.metric("30-Day Readmission Rate", f"{readm_rate:.2f}%")
    with kpi4:
        st.metric("Total Claimed Amount", f"₹{tot_claimed:,.0f}")

    st.divider()

    # =========================================================================
    # TABS INTERFACE
    # =========================================================================
    tab_ops, tab_qual, tab_fin, tab_clin = st.tabs([
        "🏥 Operations",
        "⭐ Quality",
        "💰 Finance",
        "🔬 Clinical",
    ])

    # -------------------------------------------------------------------------
    # TAB 1: OPERATIONS
    # -------------------------------------------------------------------------
    with tab_ops:
        st.subheader("Hospital Inpatient Operations & Bed Utilization")

        if f_daily.empty:
            st.info("No operational data available for the chosen date range.")
        else:
            col_l, col_r = st.columns(2)
            with col_l:
                fig_adm = create_operations_admissions_line(f_daily)
                st.plotly_chart(fig_adm, use_container_width=True)
                st.caption("Displays daily admission volumes over time across selected facilities to track patient load fluctuations.")

            with col_r:
                fig_occ = create_occupancy_bar(f_daily)
                st.plotly_chart(fig_occ, use_container_width=True)
                st.caption("Compares current hospital bed occupancy against the critical 85% operational capacity threshold.")

            fig_los = create_avg_los_bar(f_daily)
            st.plotly_chart(fig_los, use_container_width=True)
            st.caption("Highlights average length of stay in days per facility to assess bed turnover efficiency.")

    # -------------------------------------------------------------------------
    # TAB 2: QUALITY
    # -------------------------------------------------------------------------
    with tab_qual:
        st.subheader("Clinical Quality & 30-Day Readmission Tracking")

        if f_readm.empty:
            st.info("No quality and readmission records available for the selected parameters.")
        else:
            col_q1, col_q2 = st.columns(2)
            with col_q1:
                fig_rq = create_readmission_rate_bar(f_readm)
                st.plotly_chart(fig_rq, use_container_width=True)
                st.caption("Ranks facilities by overall 30-day post-discharge readmission percentage.")

            with col_q2:
                fig_rt = create_readmission_trend_line(f_readm)
                st.plotly_chart(fig_rt, use_container_width=True)
                st.caption("Tracks monthly longitudinal variation in 30-day readmissions across network hospitals.")

            st.markdown("#### Facility Readmission Adjudication Table")
            display_tbl = (
                f_readm[["hospital_name", "discharge_month", "index_discharges", "readmissions_30d", "readmission_rate_pct"]]
                .sort_values(["hospital_name", "discharge_month"])
                .rename(columns={
                    "hospital_name": "Hospital",
                    "discharge_month": "Discharge Month",
                    "index_discharges": "Discharges",
                    "readmissions_30d": "30d Readmissions",
                    "readmission_rate_pct": "Readmission Rate (%)",
                })
            )
            st.dataframe(display_tbl, use_container_width=True)
            st.caption("Granular hospital × month breakdown of index discharge counts and readmission outcomes.")

    # -------------------------------------------------------------------------
    # TAB 3: FINANCE
    # -------------------------------------------------------------------------
    with tab_fin:
        st.subheader("Claims Revenue Cycle & Insurer Adjudication")

        if f_claims.empty:
            st.info("No claims records found for the active filter selection.")
        else:
            tot_cl = float(f_claims["total_claimed"].sum())
            tot_app = float(f_claims["total_approved"].sum())
            tot_num_claims = int(f_claims["claims_count"].sum())
            tot_num_rej = int(f_claims["rejected_count"].sum())
            rej_pct = ((tot_num_rej / tot_num_claims) * 100.0) if tot_num_claims > 0 else 0.0

            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                st.metric("Total Claimed Amount", f"₹{tot_cl:,.0f}")
            with fc2:
                st.metric("Total Approved Amount", f"₹{tot_app:,.0f}")
            with fc3:
                st.metric("Overall Rejection Rate", f"{rej_pct:.2f}%")

            col_f1, col_f2 = st.columns([1, 1])
            with col_f1:
                fig_payer = create_claims_stacked_bar(f_claims)
                st.plotly_chart(fig_payer, use_container_width=True)
                st.caption("Breaks down claim resolution volumes by health insurance provider across statuses.")

            with col_f2:
                fig_rej = create_rejection_rate_bar(f_claims)
                st.plotly_chart(fig_rej, use_container_width=True)
                st.caption("Identifies disproportionate claim rejection percentages across hospital facilities and payers.")

    # -------------------------------------------------------------------------
    # TAB 4: CLINICAL
    # -------------------------------------------------------------------------
    with tab_clin:
        st.subheader("Diagnostic Pathology & Abnormality Analytics")

        if f_labs.empty:
            st.info("No lab diagnostic data matching active filter criteria.")
        else:
            col_c1, col_c2 = st.columns(2)
            with col_c1:
                fig_lab_bar = create_lab_abnormal_bar(f_labs)
                st.plotly_chart(fig_lab_bar, use_container_width=True)
                st.caption("Measures percentage of test specimens falling outside normal reference ranges by test type.")

            with col_c2:
                fig_heat = create_lab_heatmap(f_labs)
                st.plotly_chart(fig_heat, use_container_width=True)
                st.caption("Correlates pathology abnormality rates across individual hospital facilities and test categories.")

            st.markdown("#### Top 10 Hospital × Diagnostic Test Outliers by Abnormal Volume")
            top_outliers = (
                f_labs.groupby(["hospital_name", "test_name"], as_index=False)
                .agg(
                    total_tests=("tests_done", "sum"),
                    abnormal_cases=("abnormal_count", "sum"),
                )
            )
            top_outliers["abnormal_rate_pct"] = (
                (top_outliers["abnormal_cases"] / top_outliers["total_tests"]) * 100.0
            ).round(2)
            top_10 = (
                top_outliers.sort_values("abnormal_cases", ascending=False)
                .head(10)
                .rename(columns={
                    "hospital_name": "Hospital",
                    "test_name": "Diagnostic Test",
                    "total_tests": "Total Tests Done",
                    "abnormal_cases": "Abnormal Count",
                    "abnormal_rate_pct": "Abnormality Rate (%)",
                })
            )
            st.dataframe(top_10, use_container_width=True)
            st.caption("Ranks top hospital and test combinations by absolute abnormal result volume for clinical review.")


if __name__ == "__main__":
    main()
