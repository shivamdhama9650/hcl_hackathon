from typing import List, Optional
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

CHART_THEME = "plotly_white"
COLOR_PRIMARY = "#0284c7"
COLOR_SECONDARY = "#0f172a"
COLOR_ALERT = "#ef4444"
COLOR_SUCCESS = "#10b981"
COLOR_WARNING = "#f59e0b"


def create_operations_admissions_line(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    fig = px.line(
        df,
        x="date",
        y="admissions",
        color="hospital_name",
        title="Daily Admissions Trend by Hospital",
        labels={"date": "Date", "admissions": "Admissions Count", "hospital_name": "Hospital"},
        template=CHART_THEME,
    )
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def create_occupancy_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    latest_date = df["date"].max()
    latest_df = df[df["date"] == latest_date].copy()

    fig = px.bar(
        latest_df,
        x="hospital_name",
        y="occupancy_pct",
        color="occupancy_pct",
        color_continuous_scale=["#10b981", "#f59e0b", "#ef4444"],
        range_color=[0, 100],
        title=f"Bed Occupancy Rate by Hospital (as of {latest_date})",
        labels={"hospital_name": "Hospital", "occupancy_pct": "Occupancy Rate (%)"},
        template=CHART_THEME,
    )
    fig.add_hline(
        y=85.0,
        line_dash="dash",
        line_color="#dc2626",
        annotation_text="Target Ceiling (85%)",
        annotation_position="top left",
    )
    fig.update_layout(
        margin=dict(l=20, r=20, t=50, b=20),
        coloraxis_showscale=False,
    )
    return fig


def create_avg_los_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    los_by_hosp = (
        df.groupby("hospital_name", as_index=False)["avg_length_of_stay"]
        .mean()
        .round(2)
        .sort_values("avg_length_of_stay", ascending=False)
    )

    fig = px.bar(
        los_by_hosp,
        x="hospital_name",
        y="avg_length_of_stay",
        title="Average Length of Stay (Days) by Hospital",
        labels={"hospital_name": "Hospital", "avg_length_of_stay": "Average Stay (Days)"},
        color_discrete_sequence=[COLOR_PRIMARY],
        template=CHART_THEME,
        text="avg_length_of_stay",
    )
    fig.update_traces(texttemplate="%{text:.1f}d", textposition="outside")
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig


def create_readmission_rate_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    hosp_summary = (
        df.groupby("hospital_name", as_index=False)
        .agg(
            total_index=("index_discharges", "sum"),
            total_readm=("readmissions_30d", "sum"),
        )
    )
    hosp_summary["overall_rate_pct"] = (
        (hosp_summary["total_readm"] / hosp_summary["total_index"]) * 100.0
    ).round(2)
    hosp_summary = hosp_summary.sort_values("overall_rate_pct", ascending=False)

    fig = px.bar(
        hosp_summary,
        x="hospital_name",
        y="overall_rate_pct",
        title="Overall 30-Day Readmission Rate by Hospital",
        labels={"hospital_name": "Hospital", "overall_rate_pct": "Readmission Rate (%)"},
        color="overall_rate_pct",
        color_continuous_scale="Reds",
        template=CHART_THEME,
        text="overall_rate_pct",
    )
    fig.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), coloraxis_showscale=False)
    return fig


def create_readmission_trend_line(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    monthly = (
        df.groupby(["discharge_month", "hospital_name"], as_index=False)
        .agg(
            total_index=("index_discharges", "sum"),
            total_readm=("readmissions_30d", "sum"),
        )
    )
    monthly["readmission_rate_pct"] = (
        (monthly["total_readm"] / monthly["total_index"]) * 100.0
    ).round(2)

    fig = px.line(
        monthly,
        x="discharge_month",
        y="readmission_rate_pct",
        color="hospital_name",
        title="Monthly 30-Day Readmission Rate Trajectory",
        labels={"discharge_month": "Discharge Month", "readmission_rate_pct": "Readmission Rate (%)", "hospital_name": "Hospital"},
        template=CHART_THEME,
        markers=True,
    )
    fig.update_layout(
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def create_claims_stacked_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    status_cols = ["approved_count", "pending_count", "rejected_count"]
    # Melt or prepare insurer status breakdowns
    insurer_grp = (
        df.groupby("insurer", as_index=False)
        .agg(
            approved=("total_approved", lambda s: (s > 0).sum() if "total_approved" in df.columns else 0),
            rejected=("rejected_count", "sum"),
            pending=("pending_count", "sum"),
            total_claims=("claims_count", "sum"),
        )
    )
    insurer_grp["approved"] = (insurer_grp["total_claims"] - insurer_grp["rejected"] - insurer_grp["pending"]).clip(lower=0)

    fig = go.Figure()
    fig.add_trace(go.Bar(name="Approved", x=insurer_grp["insurer"], y=insurer_grp["approved"], marker_color=COLOR_SUCCESS))
    fig.add_trace(go.Bar(name="Pending", x=insurer_grp["insurer"], y=insurer_grp["pending"], marker_color=COLOR_WARNING))
    fig.add_trace(go.Bar(name="Rejected", x=insurer_grp["insurer"], y=insurer_grp["rejected"], marker_color=COLOR_ALERT))

    fig.update_layout(
        barmode="stack",
        title="Claims Volume by Insurer and Adjudication Status",
        xaxis_title="Payer / Insurer",
        yaxis_title="Total Number of Claims",
        template=CHART_THEME,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def create_rejection_rate_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    grp = (
        df.groupby(["hospital_name", "insurer"], as_index=False)
        .agg(
            total_claims=("claims_count", "sum"),
            total_rejected=("rejected_count", "sum"),
        )
    )
    grp["rejection_rate_pct"] = (
        (grp["total_rejected"] / grp["total_claims"]) * 100.0
    ).round(2)

    fig = px.bar(
        grp,
        x="hospital_name",
        y="rejection_rate_pct",
        color="insurer",
        barmode="group",
        title="Claim Rejection Rate (%) by Hospital and Insurer",
        labels={"hospital_name": "Hospital", "rejection_rate_pct": "Rejection Rate (%)", "insurer": "Insurer"},
        template=CHART_THEME,
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=50, b=20),
    )
    return fig


def create_lab_abnormal_bar(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    test_grp = (
        df.groupby("test_name", as_index=False)
        .agg(
            total_tests=("tests_done", "sum"),
            total_abnormal=("abnormal_count", "sum"),
        )
    )
    test_grp["overall_abnormal_pct"] = (
        (test_grp["total_abnormal"] / test_grp["total_tests"]) * 100.0
    ).round(2)
    test_grp = test_grp.sort_values("overall_abnormal_pct", ascending=False)

    fig = px.bar(
        test_grp,
        x="test_name",
        y="overall_abnormal_pct",
        title="Diagnostic Abnormality Rate (%) Across Network Tests",
        labels={"test_name": "Diagnostic Test", "overall_abnormal_pct": "Abnormal Results (%)"},
        color="overall_abnormal_pct",
        color_continuous_scale="Purples",
        template=CHART_THEME,
        text="overall_abnormal_pct",
    )
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20), coloraxis_showscale=False)
    return fig


def create_lab_heatmap(df: pd.DataFrame) -> go.Figure:
    if df.empty:
        return go.Figure()

    pivot = (
        df.groupby(["hospital_name", "test_name"], as_index=False)
        .agg(
            total_tests=("tests_done", "sum"),
            total_abnormal=("abnormal_count", "sum"),
        )
    )
    pivot["abnormal_pct"] = (
        (pivot["total_abnormal"] / pivot["total_tests"]) * 100.0
    ).round(2)

    heatmap_data = pivot.pivot(index="hospital_name", columns="test_name", values="abnormal_pct")

    fig = px.imshow(
        heatmap_data,
        text_auto=".1f",
        aspect="auto",
        color_continuous_scale="YlOrRd",
        title="Clinical Abnormality Heatmap: Hospital × Diagnostic Test (%)",
        labels=dict(x="Test Name", y="Hospital", color="Abnormal %"),
        template=CHART_THEME,
    )
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig
