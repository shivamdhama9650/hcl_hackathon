import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Set
import numpy as np
import pandas as pd

from src.config import setup_logger

logger = setup_logger(__name__)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
ISO_DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def evaluate_series_dates(series: pd.Series) -> int:
    violations = 0
    for val in series.dropna():
        s = str(val).strip()
        if not ISO_DATE_REGEX.match(s):
            violations += 1
    return violations


def evaluate_series_phones(series: pd.Series) -> int:
    violations = 0
    for val in series.dropna():
        s = str(val).strip()
        if not s.isdigit() or len(s) < 10 or len(s) > 12:
            violations += 1
    return violations


def evaluate_series_emails(series: pd.Series) -> int:
    violations = 0
    for val in series.dropna():
        s = str(val).strip()
        if not EMAIL_REGEX.match(s):
            violations += 1
    return violations


def profile_entity_dataframe(
    df: pd.DataFrame,
    entity_name: str,
    business_key: str,
    valid_hospital_ids: Optional[Set[str]] = None,
    valid_patient_ids: Optional[Set[str]] = None,
    valid_encounter_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    row_count = len(df)
    col_metrics: Dict[str, Dict[str, Any]] = {}
    issues: List[Dict[str, Any]] = []

    if row_count == 0:
        return {
            "entity": entity_name,
            "row_count": 0,
            "business_key": business_key,
            "duplicate_business_keys": 0,
            "columns": {},
            "violations": {},
            "orphan_fks": {},
            "top_5_issues": [],
        }

    for col in df.columns:
        s = df[col]
        null_count = int(s.isna().sum())
        null_pct = round((null_count / row_count) * 100.0, 2)

        try:
            distinct_count = int(s.nunique())
        except TypeError:
            distinct_count = int(s.astype(str).nunique())

        metric: Dict[str, Any] = {
            "null_count": null_count,
            "null_pct": null_pct,
            "distinct_count": distinct_count,
        }

        if null_count > 0:
            issues.append({
                "issue": f"Null values in column '{col}'",
                "count": null_count,
                "pct": null_pct,
                "severity": "HIGH" if col == business_key else "MEDIUM",
            })

        numeric_vals = pd.to_numeric(s, errors="coerce")
        if numeric_vals.notna().sum() > 0 and s.dtype.kind in "biufc":
            metric["min"] = float(numeric_vals.min())
            metric["max"] = float(numeric_vals.max())
            metric["mean"] = round(float(numeric_vals.mean()), 2)

        col_metrics[col] = metric

    duplicate_keys = 0
    if business_key in df.columns:
        duplicate_keys = int(df[business_key].duplicated().sum())
        if duplicate_keys > 0:
            issues.append({
                "issue": f"Duplicate business keys in '{business_key}'",
                "count": duplicate_keys,
                "pct": round((duplicate_keys / row_count) * 100.0, 2),
                "severity": "HIGH",
            })

    violations: Dict[str, int] = {}
    for col in df.columns:
        col_lower = col.lower()
        if "date" in col_lower or "dob" in col_lower:
            count = evaluate_series_dates(df[col])
            violations[f"{col}_non_iso"] = count
            if count > 0:
                issues.append({
                    "issue": f"Non-ISO date formats in '{col}'",
                    "count": count,
                    "pct": round((count / row_count) * 100.0, 2),
                    "severity": "MEDIUM",
                })
        elif "phone" in col_lower:
            count = evaluate_series_phones(df[col])
            violations[f"{col}_format_violations"] = count
            if count > 0:
                issues.append({
                    "issue": f"Unstandardized phone numbers in '{col}'",
                    "count": count,
                    "pct": round((count / row_count) * 100.0, 2),
                    "severity": "LOW",
                })
        elif "email" in col_lower:
            count = evaluate_series_emails(df[col])
            violations[f"{col}_invalid_syntax"] = count
            if count > 0:
                issues.append({
                    "issue": f"Invalid email addresses in '{col}'",
                    "count": count,
                    "pct": round((count / row_count) * 100.0, 2),
                    "severity": "LOW",
                })

    orphan_fks: Dict[str, int] = {}
    if valid_hospital_ids is not None:
        hosp_col = "hospital_id" if "hospital_id" in df.columns else ("primary_hospital_id" if "primary_hospital_id" in df.columns else None)
        if hosp_col:
            orphans = int((~df[hosp_col].isin(valid_hospital_ids) & df[hosp_col].notna()).sum())
            orphan_fks[f"{hosp_col}_orphans"] = orphans
            if orphans > 0:
                issues.append({
                    "issue": f"Orphan hospital foreign keys in '{hosp_col}'",
                    "count": orphans,
                    "pct": round((orphans / row_count) * 100.0, 2),
                    "severity": "HIGH",
                })

    if valid_patient_ids is not None and "patient_id" in df.columns and entity_name != "patients":
        orphans = int((~df["patient_id"].isin(valid_patient_ids) & df["patient_id"].notna()).sum())
        orphan_fks["patient_id_orphans"] = orphans
        if orphans > 0:
            issues.append({
                "issue": f"Orphan patient foreign keys in 'patient_id'",
                "count": orphans,
                "pct": round((orphans / row_count) * 100.0, 2),
                "severity": "HIGH",
            })

    if valid_encounter_ids is not None and "encounter_id" in df.columns and entity_name != "encounters":
        orphans = int((~df["encounter_id"].isin(valid_encounter_ids) & df["encounter_id"].notna()).sum())
        orphan_fks["encounter_id_orphans"] = orphans
        if orphans > 0:
            issues.append({
                "issue": f"Orphan encounter foreign keys in 'encounter_id'",
                "count": orphans,
                "pct": round((orphans / row_count) * 100.0, 2),
                "severity": "HIGH",
            })

    issues.sort(key=lambda x: x["count"], reverse=True)
    top_5_issues = issues[:5]

    return {
        "entity": entity_name,
        "row_count": row_count,
        "business_key": business_key,
        "duplicate_business_keys": duplicate_keys,
        "columns": col_metrics,
        "violations": violations,
        "orphan_fks": orphan_fks,
        "top_5_issues": top_5_issues,
    }


def profile_dataset(
    entities: Dict[str, pd.DataFrame],
    business_keys: Dict[str, str],
    valid_hospital_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    valid_patients: Optional[Set[str]] = None
    if "patients" in entities and not entities["patients"].empty:
        valid_patients = set(entities["patients"]["patient_id"].dropna())

    valid_encounters: Optional[Set[str]] = None
    if "encounters" in entities and not entities["encounters"].empty:
        valid_encounters = set(entities["encounters"]["encounter_id"].dropna())

    report: Dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "entities": {},
    }

    for name, df in entities.items():
        key = business_keys.get(name, "id")
        report["entities"][name] = profile_entity_dataframe(
            df=df,
            entity_name=name,
            business_key=key,
            valid_hospital_ids=valid_hospital_ids,
            valid_patient_ids=valid_patients,
            valid_encounter_ids=valid_encounters,
        )

    return report


def format_profiling_markdown(report: Dict[str, Any], title: str = "Data Profiling Report") -> str:
    lines: List[str] = [
        f"# {title}",
        f"Generated at: {report.get('timestamp')}",
        "",
    ]

    for entity, metrics in report.get("entities", {}).items():
        lines.append(f"## Entity: {entity}")
        lines.append(f"- **Total Rows:** {metrics['row_count']:,}")
        lines.append(f"- **Business Key:** `{metrics['business_key']}` (Duplicates: {metrics['duplicate_business_keys']:,})")

        lines.append("### Top Issues:")
        if metrics.get("top_5_issues"):
            for issue in metrics["top_5_issues"]:
                lines.append(f"- [{issue['severity']}] {issue['issue']}: {issue['count']} ({issue['pct']}%)")
        else:
            lines.append("- No data quality issues detected.")

        lines.append("")
        lines.append("### Column Summary:")
        lines.append("| Column | Null Count | Null % | Distinct Count |")
        lines.append("|---|---|---|---|")
        for col, col_m in metrics.get("columns", {}).items():
            lines.append(f"| {col} | {col_m['null_count']} | {col_m['null_pct']}% | {col_m['distinct_count']} |")
        lines.append("")

    return "\n".join(lines)
