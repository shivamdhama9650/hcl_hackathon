-- =====================================================================
-- MediSync Health Network: Warehouse DDL (Bronze, Silver, Gold, Vault, Audit)
-- =====================================================================

-- Bronze Layer: Raw append-only extracts
CREATE TABLE IF NOT EXISTS bronze_patients (
    patient_id TEXT,
    full_name TEXT,
    gender TEXT,
    date_of_birth TEXT,
    phone TEXT,
    email TEXT,
    national_id TEXT,
    city TEXT,
    primary_hospital_id TEXT,
    last_updated TEXT,
    batch_id TEXT,
    source_file TEXT,
    ingest_timestamp TEXT
);

CREATE TABLE IF NOT EXISTS bronze_encounters (
    encounter_id TEXT,
    patient_id TEXT,
    hospital_id TEXT,
    department TEXT,
    encounter_type TEXT,
    admit_date TEXT,
    discharge_date TEXT,
    diagnosis TEXT,
    primary_diagnosis_code TEXT,
    attending_doctor_id TEXT,
    last_updated TEXT,
    batch_id TEXT,
    source_file TEXT,
    ingest_timestamp TEXT
);

CREATE TABLE IF NOT EXISTS bronze_lab_results (
    lab_result_id TEXT,
    encounter_id TEXT,
    test_name TEXT,
    result_value TEXT,
    unit TEXT,
    reference_low REAL,
    reference_high REAL,
    result_timestamp TEXT,
    last_updated TEXT,
    batch_id TEXT,
    source_file TEXT,
    ingest_timestamp TEXT
);

CREATE TABLE IF NOT EXISTS bronze_claims (
    claim_id TEXT,
    encounter_id TEXT,
    insurer TEXT,
    claim_amount REAL,
    approved_amount REAL,
    claim_status TEXT,
    claim_date TEXT,
    last_updated TEXT,
    batch_id TEXT,
    source_file TEXT,
    ingest_timestamp TEXT
);

-- Silver Layer: Cleansed, typed, deduplicated, masked
CREATE TABLE IF NOT EXISTS silver_patients (
    patient_id TEXT PRIMARY KEY,
    original_patient_id TEXT,
    full_name TEXT,
    gender TEXT,
    age_band TEXT,
    patient_age INTEGER,
    phone TEXT,
    email TEXT,
    national_id TEXT,
    city TEXT,
    primary_hospital_id TEXT,
    last_updated TEXT,
    batch_id TEXT
);

CREATE TABLE IF NOT EXISTS silver_encounters (
    encounter_id TEXT PRIMARY KEY,
    patient_id TEXT,
    original_patient_id TEXT,
    hospital_id TEXT,
    department TEXT,
    encounter_type TEXT,
    admit_date TEXT,
    discharge_date TEXT,
    length_of_stay_days INTEGER,
    primary_diagnosis_code TEXT,
    attending_doctor_id TEXT,
    last_updated TEXT,
    batch_id TEXT
);

CREATE TABLE IF NOT EXISTS silver_lab_results (
    lab_result_id TEXT PRIMARY KEY,
    encounter_id TEXT,
    test_name TEXT,
    test_code TEXT,
    result_value TEXT,
    unit TEXT,
    reference_low REAL,
    reference_high REAL,
    lab_flag TEXT,
    result_timestamp TEXT,
    result_date TEXT,
    last_updated TEXT,
    batch_id TEXT
);

CREATE TABLE IF NOT EXISTS silver_claims (
    claim_id TEXT PRIMARY KEY,
    encounter_id TEXT,
    insurer TEXT,
    claim_amount REAL,
    approved_amount REAL,
    claim_status TEXT,
    claim_date TEXT,
    last_updated TEXT,
    batch_id TEXT
);

-- Restricted PII Vault Table
CREATE TABLE IF NOT EXISTS pii_vault (
    patient_id_token TEXT PRIMARY KEY,
    original_patient_id TEXT,
    full_name TEXT,
    phone TEXT,
    email TEXT,
    national_id TEXT,
    date_of_birth TEXT,
    batch_id TEXT,
    created_at TEXT
);

-- Quarantine Table
CREATE TABLE IF NOT EXISTS quarantine_records (
    quarantine_id TEXT PRIMARY KEY,
    entity TEXT,
    business_key TEXT,
    reason TEXT,
    batch_id TEXT,
    record_payload TEXT,
    quarantine_timestamp TEXT
);

-- Audit Table
CREATE TABLE IF NOT EXISTS batch_audit (
    batch_id TEXT,
    started_at TEXT,
    finished_at TEXT,
    rows_read INTEGER,
    rows_loaded INTEGER,
    rows_quarantined INTEGER,
    rows_superseded INTEGER,
    status TEXT,
    error_message TEXT
);

-- Gold Tables
CREATE TABLE IF NOT EXISTS gold_hospital_daily_admissions (
    hospital_id TEXT,
    admission_date TEXT,
    admissions INTEGER,
    unique_patients INTEGER,
    PRIMARY KEY (hospital_id, admission_date)
);

CREATE TABLE IF NOT EXISTS gold_readmission_30d (
    hospital_id TEXT,
    discharge_month TEXT,
    discharges INTEGER,
    readmissions_30d INTEGER,
    readmission_rate REAL,
    PRIMARY KEY (hospital_id, discharge_month)
);

CREATE TABLE IF NOT EXISTS gold_claims_summary (
    hospital_id TEXT,
    claim_month TEXT,
    total_claims INTEGER,
    total_claim_amount REAL,
    avg_claim_amount REAL,
    approved_claims INTEGER,
    pending_claims INTEGER,
    rejected_claims INTEGER,
    approved_amount REAL,
    PRIMARY KEY (hospital_id, claim_month)
);

CREATE TABLE IF NOT EXISTS gold_lab_abnormality (
    hospital_id TEXT,
    test_code TEXT,
    test_name TEXT,
    total_tests INTEGER,
    abnormal_tests INTEGER,
    abnormality_rate REAL,
    PRIMARY KEY (hospital_id, test_code)
);
