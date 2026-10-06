-- =====================================================================
-- MediSync Health Network: Row-Level Security (RLS) Portable Views
-- Parameterized by session context stored in session_context table
-- =====================================================================

CREATE TABLE IF NOT EXISTS session_context (
    current_user TEXT PRIMARY KEY
);

-- Default session user if none set
INSERT OR IGNORE INTO session_context (current_user) VALUES ('engineer_user');

-- 1. Secure Patients View
-- Compliance Auditor: sees all rows unmasked via pii_vault
-- Regional Analyst: sees own region patients only, masked
-- Hospital Manager: sees own hospital patients only, masked
-- Data Engineer: sees all rows across all regions, masked
CREATE VIEW IF NOT EXISTS v_secure_patients AS
SELECT
    CASE
        WHEN u.role = 'COMPLIANCE_AUDITOR' THEN COALESCE(v.original_patient_id, p.original_patient_id)
        ELSE p.patient_id
    END AS patient_id,
    CASE
        WHEN u.role = 'COMPLIANCE_AUDITOR' THEN COALESCE(v.full_name, p.full_name)
        ELSE p.full_name
    END AS full_name,
    p.gender,
    CASE
        WHEN u.role = 'COMPLIANCE_AUDITOR' THEN COALESCE(v.date_of_birth, p.age_band)
        ELSE p.age_band
    END AS date_of_birth_or_age_band,
    p.patient_age,
    CASE
        WHEN u.role = 'COMPLIANCE_AUDITOR' THEN COALESCE(v.phone, p.phone)
        ELSE p.phone
    END AS phone,
    CASE
        WHEN u.role = 'COMPLIANCE_AUDITOR' THEN COALESCE(v.email, p.email)
        ELSE p.email
    END AS email,
    CASE
        WHEN u.role = 'COMPLIANCE_AUDITOR' THEN COALESCE(v.national_id, p.national_id)
        ELSE p.national_id
    END AS national_id,
    p.city,
    p.primary_hospital_id,
    h.region,
    p.last_updated
FROM silver_patients p
LEFT JOIN pii_vault v ON p.original_patient_id = v.original_patient_id
LEFT JOIN reference_hospitals h ON p.primary_hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND p.primary_hospital_id = u.hospital_id);

-- 2. Secure Encounters View
CREATE VIEW IF NOT EXISTS v_secure_encounters AS
SELECT
    e.encounter_id,
    e.patient_id,
    e.hospital_id,
    h.hospital_name,
    h.region,
    e.department,
    e.encounter_type,
    e.admit_date,
    e.discharge_date,
    e.length_of_stay_days,
    e.primary_diagnosis_code,
    e.attending_doctor_id,
    e.last_updated
FROM silver_encounters e
LEFT JOIN reference_hospitals h ON e.hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND e.hospital_id = u.hospital_id);

-- 3. Secure Lab Results View
CREATE VIEW IF NOT EXISTS v_secure_lab_results AS
SELECT
    l.lab_result_id,
    l.encounter_id,
    e.hospital_id,
    h.region,
    l.test_code,
    l.test_name,
    l.result_value,
    l.unit,
    l.reference_low,
    l.reference_high,
    l.lab_flag,
    l.result_timestamp,
    l.result_date,
    l.last_updated
FROM silver_lab_results l
JOIN silver_encounters e ON l.encounter_id = e.encounter_id
LEFT JOIN reference_hospitals h ON e.hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND e.hospital_id = u.hospital_id);

-- 4. Secure Claims View
CREATE VIEW IF NOT EXISTS v_secure_claims AS
SELECT
    c.claim_id,
    c.encounter_id,
    e.hospital_id,
    h.region,
    c.insurer,
    c.claim_amount,
    c.approved_amount,
    c.claim_status,
    c.claim_date,
    c.last_updated
FROM silver_claims c
JOIN silver_encounters e ON c.encounter_id = e.encounter_id
LEFT JOIN reference_hospitals h ON e.hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND e.hospital_id = u.hospital_id);

-- 5. Secure Gold Daily Admissions View
CREATE VIEW IF NOT EXISTS v_secure_gold_hospital_daily_admissions AS
SELECT
    g.hospital_id,
    h.hospital_name,
    h.region,
    g.admission_date,
    g.admissions,
    g.unique_patients
FROM gold_hospital_daily_admissions g
LEFT JOIN reference_hospitals h ON g.hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND g.hospital_id = u.hospital_id);

-- 6. Secure Gold 30-Day Readmissions View
CREATE VIEW IF NOT EXISTS v_secure_gold_readmission_30d AS
SELECT
    g.hospital_id,
    h.hospital_name,
    h.region,
    g.discharge_month,
    g.discharges,
    g.readmissions_30d,
    g.readmission_rate
FROM gold_readmission_30d g
LEFT JOIN reference_hospitals h ON g.hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND g.hospital_id = u.hospital_id);

-- 7. Secure Gold Claims Summary View
CREATE VIEW IF NOT EXISTS v_secure_gold_claims_summary AS
SELECT
    g.hospital_id,
    h.hospital_name,
    h.region,
    g.claim_month,
    g.total_claims,
    g.total_claim_amount,
    g.avg_claim_amount,
    g.approved_claims,
    g.pending_claims,
    g.rejected_claims,
    g.approved_amount
FROM gold_claims_summary g
LEFT JOIN reference_hospitals h ON g.hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND g.hospital_id = u.hospital_id);

-- 8. Secure Gold Lab Abnormality View
CREATE VIEW IF NOT EXISTS v_secure_gold_lab_abnormality AS
SELECT
    g.hospital_id,
    h.hospital_name,
    h.region,
    g.test_code,
    g.test_name,
    g.total_tests,
    g.abnormal_tests,
    g.abnormality_rate
FROM gold_lab_abnormality g
LEFT JOIN reference_hospitals h ON g.hospital_id = h.hospital_id
CROSS JOIN session_context sc
LEFT JOIN reference_user_access u ON sc.current_user = u.user_name
WHERE
    u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
    OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
    OR (u.role = 'HOSPITAL_MANAGER' AND g.hospital_id = u.hospital_id);
