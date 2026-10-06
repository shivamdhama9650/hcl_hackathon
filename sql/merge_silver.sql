-- =====================================================================
-- MediSync Health Network: MERGE INTO Statements for Silver Upserts
-- Used in Notebook 03_silver_quarantine.py and Databricks SQL Workflows
-- =====================================================================

-- 1. MERGE Patients
MERGE INTO silver_patients AS target
USING staged_silver_patients AS source
ON target.original_patient_id = source.original_patient_id
WHEN MATCHED AND source.last_updated > target.last_updated THEN
  UPDATE SET
    target.patient_id = source.patient_id,
    target.full_name = source.full_name,
    target.gender = source.gender,
    target.age_band = source.age_band,
    target.patient_age = source.patient_age,
    target.phone = source.phone,
    target.email = source.email,
    target.national_id = source.national_id,
    target.city = source.city,
    target.primary_hospital_id = source.primary_hospital_id,
    target.last_updated = source.last_updated,
    target.batch_id = source.batch_id
WHEN NOT MATCHED THEN
  INSERT (
    patient_id, original_patient_id, full_name, gender, age_band,
    patient_age, phone, email, national_id, city, primary_hospital_id,
    last_updated, batch_id
  )
  VALUES (
    source.patient_id, source.original_patient_id, source.full_name, source.gender, source.age_band,
    source.patient_age, source.phone, source.email, source.national_id, source.city, source.primary_hospital_id,
    source.last_updated, source.batch_id
  );

-- 2. MERGE Encounters
MERGE INTO silver_encounters AS target
USING staged_silver_encounters AS source
ON target.encounter_id = source.encounter_id
WHEN MATCHED AND source.last_updated > target.last_updated THEN
  UPDATE SET
    target.patient_id = source.patient_id,
    target.original_patient_id = source.original_patient_id,
    target.hospital_id = source.hospital_id,
    target.department = source.department,
    target.encounter_type = source.encounter_type,
    target.admit_date = source.admit_date,
    target.discharge_date = source.discharge_date,
    target.length_of_stay_days = source.length_of_stay_days,
    target.primary_diagnosis_code = source.primary_diagnosis_code,
    target.attending_doctor_id = source.attending_doctor_id,
    target.last_updated = source.last_updated,
    target.batch_id = source.batch_id
WHEN NOT MATCHED THEN
  INSERT (
    encounter_id, patient_id, original_patient_id, hospital_id, department,
    encounter_type, admit_date, discharge_date, length_of_stay_days,
    primary_diagnosis_code, attending_doctor_id, last_updated, batch_id
  )
  VALUES (
    source.encounter_id, source.patient_id, source.original_patient_id, source.hospital_id, source.department,
    source.encounter_type, source.admit_date, source.discharge_date, source.length_of_stay_days,
    source.primary_diagnosis_code, source.attending_doctor_id, source.last_updated, source.batch_id
  );

-- 3. MERGE Lab Results
MERGE INTO silver_lab_results AS target
USING staged_silver_lab_results AS source
ON target.lab_result_id = source.lab_result_id
WHEN MATCHED AND source.last_updated > target.last_updated THEN
  UPDATE SET
    target.encounter_id = source.encounter_id,
    target.test_name = source.test_name,
    target.test_code = source.test_code,
    target.result_value = source.result_value,
    target.unit = source.unit,
    target.reference_low = source.reference_low,
    target.reference_high = source.reference_high,
    target.lab_flag = source.lab_flag,
    target.result_timestamp = source.result_timestamp,
    target.result_date = source.result_date,
    target.last_updated = source.last_updated,
    target.batch_id = source.batch_id
WHEN NOT MATCHED THEN
  INSERT (
    lab_result_id, encounter_id, test_name, test_code, result_value,
    unit, reference_low, reference_high, lab_flag, result_timestamp,
    result_date, last_updated, batch_id
  )
  VALUES (
    source.lab_result_id, source.encounter_id, source.test_name, source.test_code, source.result_value,
    source.unit, source.reference_low, source.reference_high, source.lab_flag, source.result_timestamp,
    source.result_date, source.last_updated, source.batch_id
  );

-- 4. MERGE Claims
MERGE INTO silver_claims AS target
USING staged_silver_claims AS source
ON target.claim_id = source.claim_id
WHEN MATCHED AND source.last_updated > target.last_updated THEN
  UPDATE SET
    target.encounter_id = source.encounter_id,
    target.insurer = source.insurer,
    target.claim_amount = source.claim_amount,
    target.approved_amount = source.approved_amount,
    target.claim_status = source.claim_status,
    target.claim_date = source.claim_date,
    target.last_updated = source.last_updated,
    target.batch_id = source.batch_id
WHEN NOT MATCHED THEN
  INSERT (
    claim_id, encounter_id, insurer, claim_amount, approved_amount,
    claim_status, claim_date, last_updated, batch_id
  )
  VALUES (
    source.claim_id, source.encounter_id, source.insurer, source.claim_amount, source.approved_amount,
    source.claim_status, source.claim_date, source.last_updated, source.batch_id
  );
