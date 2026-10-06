import datetime
import logging
import re
from typing import Dict, Optional
import pandas as pd

from src.config import setup_logger

logger = setup_logger(__name__)

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

SUPPORTED_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
    "%Y/%m/%d",
    "%Y-%m-%d %H:%M:%S",
    "%d-%m-%Y",
]


def parse_date_to_iso(date_val: Optional[object]) -> Optional[str]:
    if date_val is None or pd.isna(date_val):
        return None

    if isinstance(date_val, (datetime.datetime, datetime.date, pd.Timestamp)):
        return date_val.strftime("%Y-%m-%d")

    s = str(date_val).strip()
    if not s:
        return None

    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            datetime.date.fromisoformat(s)
            return s
        except ValueError:
            return None

    for fmt in SUPPORTED_DATE_FORMATS:
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    try:
        dt = pd.to_datetime(s, format="mixed", dayfirst=False)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def cleanse_gender(gender_val: Optional[object]) -> str:
    if gender_val is None or pd.isna(gender_val):
        return "U"

    s = str(gender_val).strip().upper()
    if s in ["M", "MALE"]:
        return "M"
    if s in ["F", "FEMALE"]:
        return "F"
    if s in ["O", "OTHER"]:
        return "O"
    return "U"


def cleanse_name(name_val: Optional[object]) -> Optional[str]:
    if name_val is None or pd.isna(name_val):
        return None

    s = str(name_val).strip()
    if not s:
        return None

    return " ".join(s.split()).title()


def cleanse_phone(phone_val: Optional[object]) -> Optional[str]:
    if phone_val is None or pd.isna(phone_val):
        return None

    s = str(phone_val).strip()
    digits = re.sub(r"\D", "", s)
    return digits if digits else None


def cleanse_email(email_val: Optional[object]) -> Optional[str]:
    if email_val is None or pd.isna(email_val):
        return None

    s = str(email_val).strip().lower()
    if EMAIL_REGEX.match(s):
        return s
    return None


def compute_patient_age(dob_iso: Optional[str], as_of_date: Optional[datetime.date] = None) -> Optional[int]:
    if dob_iso is None:
        return None

    ref_date = as_of_date or datetime.date.today()
    try:
        dob = datetime.date.fromisoformat(dob_iso)
        age = ref_date.year - dob.year - ((ref_date.month, ref_date.day) < (dob.month, dob.day))
        return max(0, age)
    except ValueError:
        return None


def compute_age_band(dob_iso: Optional[str], as_of_date: Optional[datetime.date] = None) -> str:
    age = compute_patient_age(dob_iso, as_of_date)
    if age is None:
        return "Unknown"

    lower = (age // 10) * 10
    upper = lower + 9
    return f"{lower}-{upper}"


def compute_length_of_stay(admit_date_iso: Optional[str], discharge_date_iso: Optional[str]) -> Optional[int]:
    if admit_date_iso is None or discharge_date_iso is None or pd.isna(admit_date_iso) or pd.isna(discharge_date_iso):
        return None

    try:
        admit = datetime.date.fromisoformat(str(admit_date_iso))
        discharge = datetime.date.fromisoformat(str(discharge_date_iso))
        diff = (discharge - admit).days
        return diff
    except (ValueError, TypeError):
        return None


def compute_lab_flag(
    result_value: Optional[object],
    reference_low: Optional[float],
    reference_high: Optional[float],
) -> str:
    if result_value is None or pd.isna(result_value):
        return "abnormal"

    try:
        num_val = float(str(result_value).strip())
    except (ValueError, TypeError):
        return "abnormal"

    if reference_low is not None and reference_high is not None:
        if reference_low <= num_val <= reference_high:
            return "normal"
        return "abnormal"

    return "normal"


def standardize_claim_status(status_val: Optional[object]) -> str:
    if status_val is None or pd.isna(status_val):
        return "Pending"

    s = str(status_val).strip().upper()
    if "APPROV" in s:
        return "Approved"
    if "REJECT" in s:
        return "Rejected"
    if "PEND" in s:
        return "Pending"
    return s.title()


def standardize_test_name(test_name_val: Optional[object]) -> str:
    if test_name_val is None or pd.isna(test_name_val):
        return "UNKNOWN"

    s = str(test_name_val).strip()
    clean = re.sub(r"\s+", " ", s)
    return clean.upper()


CANONICAL_INSURERS: Dict[str, str] = {
    # Star Health
    "star health": "Star Health",
    "star-health": "Star Health",
    "star health insurance": "Star Health",
    "star-health insurance": "Star Health",
    # ICICI Lombard
    "icici lombard": "ICICI Lombard",
    "icici-lombard": "ICICI Lombard",
    "icici lombard insurance": "ICICI Lombard",
    # HDFC ERGO
    "hdfc ergo": "HDFC ERGO",
    "hdfc-ergo": "HDFC ERGO",
    "hdfc ergo insurance": "HDFC ERGO",
    # Bajaj Allianz
    "bajaj allianz": "Bajaj Allianz",
    "bajaj-allianz": "Bajaj Allianz",
    "bajaj allianz insurance": "Bajaj Allianz",
    # Care Health
    "care health": "Care Health",
    "care-health": "Care Health",
    "care health insurance": "Care Health",
    # Niva Bupa
    "niva bupa": "Niva Bupa",
    "niva-bupa": "Niva Bupa",
    "niva bupa insurance": "Niva Bupa",
    "max bupa": "Niva Bupa",
}


def cleanse_insurer(insurer_val: Optional[object]) -> str:
    if insurer_val is None or pd.isna(insurer_val):
        return "Unknown"

    s = str(insurer_val).strip()
    if not s:
        return "Unknown"

    norm = re.sub(r"\s+", " ", s.lower().replace("_", " ")).strip()
    if norm in CANONICAL_INSURERS:
        return CANONICAL_INSURERS[norm]

    if "star" in norm:
        return "Star Health"
    if "icici" in norm:
        return "ICICI Lombard"
    if "hdfc" in norm:
        return "HDFC ERGO"
    if "bajaj" in norm:
        return "Bajaj Allianz"
    if "care" in norm:
        return "Care Health"
    if "niva" in norm or "bupa" in norm:
        return "Niva Bupa"

    return s.title()

