-- =====================================================================
-- MediSync Health Network: Databricks Unity Catalog Governance Policies
-- Row-level filters and column-level masking rules
-- =====================================================================

-- 1. User Context Lookup Function
CREATE OR REPLACE FUNCTION medisync_get_user_scope()
RETURNS TABLE(role STRING, hospital_id STRING, region STRING)
RETURN
  SELECT role, hospital_id, region
  FROM medisync_catalog.governance.user_access
  WHERE user_name = CURRENT_USER();

-- 2. Row Filter Functions
CREATE OR REPLACE FUNCTION medisync_row_filter_hospital(row_hospital_id STRING)
RETURNS BOOLEAN
RETURN
  IS_ACCOUNT_GROUP_MEMBER('compliance_auditors')
  OR IS_ACCOUNT_GROUP_MEMBER('data_engineers')
  OR EXISTS (
    SELECT 1
    FROM medisync_catalog.governance.user_access u
    LEFT JOIN medisync_catalog.governance.hospitals h ON h.hospital_id = row_hospital_id
    WHERE u.user_name = CURRENT_USER()
      AND (
        u.role IN ('COMPLIANCE_AUDITOR', 'DATA_ENGINEER')
        OR (u.role = 'REGIONAL_ANALYST' AND h.region = u.region)
        OR (u.role = 'HOSPITAL_MANAGER' AND u.hospital_id = row_hospital_id)
      )
  );

-- 3. Column Masking Functions (Exempting compliance_auditors)

-- Full Name Masking Policy
CREATE OR REPLACE FUNCTION medisync_mask_full_name(val STRING)
RETURNS STRING
RETURN
  CASE
    WHEN IS_ACCOUNT_GROUP_MEMBER('compliance_auditors') THEN val
    WHEN val IS NULL OR LENGTH(TRIM(val)) = 0 THEN '***'
    ELSE CONCAT(UPPER(SUBSTRING(TRIM(val), 1, 1)), '***')
  END;

-- Phone Masking Policy
CREATE OR REPLACE FUNCTION medisync_mask_phone(val STRING)
RETURNS STRING
RETURN
  CASE
    WHEN IS_ACCOUNT_GROUP_MEMBER('compliance_auditors') THEN val
    WHEN val IS NULL THEN '******'
    ELSE CONCAT('******', RIGHT(REGEXP_REPLACE(val, '[^0-9]', ''), 4))
  END;

-- Email Masking Policy
CREATE OR REPLACE FUNCTION medisync_mask_email(val STRING)
RETURNS STRING
RETURN
  CASE
    WHEN IS_ACCOUNT_GROUP_MEMBER('compliance_auditors') THEN val
    WHEN val IS NULL THEN NULL
    WHEN INSTR(val, '@') = 0 THEN '***'
    ELSE CONCAT(SUBSTRING(val, 1, 1), '***@', SPLIT_PART(val, '@', 2))
  END;

-- National ID Masking Policy
CREATE OR REPLACE FUNCTION medisync_mask_national_id(val STRING)
RETURNS STRING
RETURN
  CASE
    WHEN IS_ACCOUNT_GROUP_MEMBER('compliance_auditors') THEN val
    WHEN val IS NULL THEN '********'
    ELSE CONCAT('********', RIGHT(val, 4))
  END;

-- Date of Birth Masking Policy (Transformed to 10-year age band)
CREATE OR REPLACE FUNCTION medisync_mask_dob(val STRING)
RETURNS STRING
RETURN
  CASE
    WHEN IS_ACCOUNT_GROUP_MEMBER('compliance_auditors') THEN val
    WHEN val IS NULL THEN 'Unknown'
    ELSE CONCAT(
      CAST(FLOOR(DATEDIFF(CURRENT_DATE(), TO_DATE(val)) / 365.25 / 10) * 10 AS STRING),
      '-',
      CAST(FLOOR(DATEDIFF(CURRENT_DATE(), TO_DATE(val)) / 365.25 / 10) * 10 + 9 AS STRING)
    )
  END;

-- Patient ID Tokenization Masking Policy
CREATE OR REPLACE FUNCTION medisync_mask_patient_id(val STRING)
RETURNS STRING
RETURN
  CASE
    WHEN IS_ACCOUNT_GROUP_MEMBER('compliance_auditors') THEN val
    ELSE SHA2(CONCAT(SECRET('medisync_secrets', 'medisync_salt'), val), 256)
  END;

-- 4. Apply Policies to Silver Tables in Unity Catalog

-- Apply Row Filters
ALTER TABLE medisync_catalog.silver.silver_encounters
SET ROW FILTER medisync_row_filter_hospital ON (hospital_id);

ALTER TABLE medisync_catalog.silver.silver_patients
SET ROW FILTER medisync_row_filter_hospital ON (primary_hospital_id);

-- Apply Column Masks to Silver Patients
ALTER TABLE medisync_catalog.silver.silver_patients
ALTER COLUMN full_name SET MASK medisync_mask_full_name;

ALTER TABLE medisync_catalog.silver.silver_patients
ALTER COLUMN phone SET MASK medisync_mask_phone;

ALTER TABLE medisync_catalog.silver.silver_patients
ALTER COLUMN email SET MASK medisync_mask_email;

ALTER TABLE medisync_catalog.silver.silver_patients
ALTER COLUMN national_id SET MASK medisync_mask_national_id;

-- Note: date_of_birth is removed from Silver (transformed to age_band and patient_age).
-- The raw date_of_birth is isolated in the secure vault schema.

ALTER TABLE medisync_catalog.silver.silver_patients
ALTER COLUMN original_patient_id SET MASK medisync_mask_patient_id;
