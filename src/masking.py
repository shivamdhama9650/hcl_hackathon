import datetime
import hashlib
from typing import Optional

from src.cleanse import compute_age_band


def mask_full_name(full_name: Optional[str]) -> str:
    if not full_name:
        return "***"
    stripped = full_name.strip()
    if not stripped:
        return "***"
    return f"{stripped[0].upper()}***"


def mask_phone(phone: Optional[str]) -> str:
    if not phone:
        return "******"
    digits = "".join(filter(str.isdigit, str(phone)))
    if len(digits) <= 4:
        return f"******{digits}"
    return f"******{digits[-4:]}"


def mask_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    s = email.strip()
    if "@" not in s:
        return "***"
    local_part, domain = s.split("@", 1)
    first_char = local_part[0] if local_part else ""
    return f"{first_char}***@{domain}"


def mask_national_id(national_id: Optional[object]) -> str:
    if national_id is None:
        return "********"
    s = str(national_id).strip()
    if not s:
        return "********"
    if len(s) <= 4:
        return f"****{s}"
    prefix = "*" * (len(s) - 4)
    return f"{prefix}{s[-4:]}"


def mask_date_of_birth(dob_iso: Optional[str], as_of_date: Optional[datetime.date] = None) -> str:
    return compute_age_band(dob_iso, as_of_date)


def tokenize_patient_id(patient_id: str, salt: str) -> str:
    if not patient_id:
        return ""
    token_source = f"{salt}{str(patient_id).strip()}"
    return hashlib.sha256(token_source.encode("utf-8")).hexdigest()
