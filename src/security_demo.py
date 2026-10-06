import sqlite3
from typing import Dict, List, Tuple
import pandas as pd

from src.config import AppConfig, get_config, setup_logger

logger = setup_logger(__name__)


def set_session_user(conn: sqlite3.Connection, user_name: str) -> None:
    cursor = conn.cursor()
    cursor.execute("DELETE FROM session_context;")
    cursor.execute("INSERT INTO session_context (current_user) VALUES (?);", (user_name,))
    conn.commit()


def run_security_demo(config: AppConfig) -> List[Dict[str, object]]:
    if not config.sqlite_db_path.is_file():
        raise FileNotFoundError(f"Database file not found at {config.sqlite_db_path}. Run a batch first.")

    conn = sqlite3.connect(config.sqlite_db_path)
    test_roles: List[Tuple[str, str]] = [
        ("mgr_h01", "Hospital Manager (H01 Pune)"),
        ("analyst_west", "Regional Analyst (West Region)"),
        ("engineer_user", "Data Engineer (Full Network Masked)"),
        ("auditor_user", "Compliance Auditor (Full Network Unmasked)"),
    ]

    results: List[Dict[str, object]] = []

    try:
        for user_name, label in test_roles:
            set_session_user(conn, user_name)

            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM v_secure_encounters;")
            enc_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM v_secure_patients;")
            pat_count = cursor.fetchone()[0]

            cursor.execute("SELECT patient_id, full_name, date_of_birth_or_age_band FROM v_secure_patients LIMIT 1;")
            sample_patient = cursor.fetchone()

            results.append({
                "user_name": user_name,
                "role_label": label,
                "encounters_count": enc_count,
                "patients_count": pat_count,
                "sample_patient_id": sample_patient[0] if sample_patient else "",
                "sample_patient_name": sample_patient[1] if sample_patient else "",
                "sample_patient_dob_or_band": sample_patient[2] if sample_patient else "",
            })

            logger.info(
                "RLS Simulation [%s / %s]: encounters=%d, patients=%d | Sample: id=%s, name=%s, dob/band=%s",
                user_name,
                label,
                enc_count,
                pat_count,
                sample_patient[0] if sample_patient else "",
                sample_patient[1] if sample_patient else "",
                sample_patient[2] if sample_patient else "",
            )
    finally:
        conn.close()

    return results


if __name__ == "__main__":
    cfg = get_config()
    run_security_demo(cfg)
