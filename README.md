# MediSync Health Network: Governed Data Platform

Production-grade medallion lakehouse platform for **MediSync Health Network**, unifying synthetic healthcare extracts across 6 hospitals, 3 geographic regions, and 4 file formats into Bronze, Silver, and Gold layers with row-level security and column-level masking.

---

## 1. Architecture Overview (10 Stages)

```
[DATA_ROOT (External Source)]
            │
            ▼ (Stage 2: Byte-Identical Copy)
       [landing/]
            │
            ▼ (Stage 3: 4 Format Readers)
    [Bronze Layer] ──▶ (Stage 4: Profiler) ──▶ Structured Metrics & Top-5 Issues
            │
            ▼ (Stage 5 & 6: Cleanse, Dedupe, Watermark, Mask)
 ┌───────────────────────────┬───────────────────────────┐
 │                           │                           │
 ▼                           ▼                           ▼
[Silver Layer]         [Quarantine Layer]         [PII Vault]
(Cleansed, Typed,      (Rejection Reasons:        (Restricted AES/
 Deduplicated, Masked)  BAD_DATE, ORPHAN_FK, etc)  Tokenized Store)
 │                           │
 ├── (Reconciliation Invariant Checked: Bronze == Silver + Quarantined + Superseded)
 │
 ▼ (Stage 7: Row-Level Security & Column Masking Policies)
[Portable SQL Views / Databricks Unity Catalog]
 │
 ▼ (Stage 8: Analytics Aggregations Rebuilt Every Run)
[Gold Layer]
 ├── gold_hospital_daily_admissions (Grain: hospital_id × admission_date)
 ├── gold_readmission_30d (Grain: hospital_id × discharge_month)
 ├── gold_claims_summary (Grain: hospital_id × claim_month)
 └── gold_lab_abnormality (Grain: hospital_id × test_code)
 │
 ▼ (Stage 9: Audit & Execution Logging)
[batch_audit Table]
```

### Stage Summary
1. **Input Pack**: Batch folders (`batch_0_day1`, `batch_1_day2`, `batch_2_day3`) and static reference data (`hospitals.csv`, `user_access_json.txt`).
2. **Landing Layer**: Byte-identical copy of raw files from `DATA_ROOT` into `./landing/`. Source files in `DATA_ROOT` are never modified.
3. **Bronze Layer**: Raw entity extracts stored as append-only Parquet files and SQLite tables (`bronze_patients`, `bronze_encounters`, `bronze_lab_results`, `bronze_claims`), stamped with `batch_id`, `source_file`, and `ingest_timestamp`. Duplicates retained.
4. **Data Profiling**: Deep diagnostic scan on row counts, null percentages, distinct values, min/max/mean, duplicate primary keys, date/phone/email anomalies, and foreign key orphans. Emits top 5 data quality issues.
5. **Silver Layer & Quarantine**: Standardized, typed, and deduplicated records. Invalid records routed to `quarantine_records` with reasons (`BAD_DATE_FORMAT`, `ORPHAN_FK`, `NULL_BUSINESS_KEY`). Deduplication keeps `max(last_updated)`; losers counted as `superseded`. Watermarking skips re-delivered records.
6. **PII Masking & Vault**: 6 PII fields masked in Silver (`full_name`, `phone`, `email`, `national_id`, `date_of_birth` age bands, `patient_id` tokenized with salted SHA-256). Raw values archived in restricted `pii_vault`.
7. **Security Layer (RLS)**: Portable views (`sql/rls_views.sql`) and Databricks Unity Catalog policies (`sql/unity_catalog_policies.sql`) implementing role-based access for Compliance Auditor, Regional Analyst, Hospital Manager, and Data Engineer.
8. **Gold Layer**: Four analytics tables rebuilt every run with zero PII columns.
9. **Orchestration & Audit**: Parameterized `run_batch(batch_id)` execution logging `batch_audit` rows. Idempotent re-runs.
10. **Deliverables**: Source code, test suite, SQL scripts, Databricks notebooks, profiling reports, and documentation.

---

## 2. Local Environment Setup

### Prerequisites
- Python 3.10+
- Virtual environment tool (`venv` or `conda`)

### Step 1: Clone and Create Virtual Environment
```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Update `.env` with your parameters:
```ini
DATA_ROOT=C:/Users/Shiva/OneDrive/Desktop/hackatoons/MediaSync_Source_Data
MEDISYNC_SALT=f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4
WAREHOUSE_PATH=./warehouse
LANDING_PATH=./landing
LOG_LEVEL=INFO
```

---

## 3. Running the Pipeline Locally

### Run Individual Batches
```bash
# Day 1: Full historical load
python -m src.pipeline --batch batch_0

# Day 2: Incremental new and updated records
python -m src.pipeline --batch batch_1

# Day 3: Idempotency test (duplicates, re-delivered day 2 file)
python -m src.pipeline --batch batch_2
```

### Run All Batches Sequentially
```bash
python -m src.pipeline --batch all
```

### Run Automated Test Suite
```bash
pytest tests/test_pipeline.py -v
```

---

## 4. Row-Level Security (RLS) Verification Demo

To demonstrate the four role-based access levels, run the simulation script:
```bash
python -m src.security_demo
```

### Expected Output
| User Role | User Name | Filter Scope | Masking Level | Encounters Count | Patients Count |
|---|---|---|---|---|---|
| **Hospital Manager** | `mgr_h01` | Hospital H01 (Pune) | Masked | 2,742 | 636 |
| **Regional Analyst** | `analyst_west` | West Region (H01 + H02) | Masked | 5,789 | 1,410 |
| **Data Engineer** | `engineer_user` | All Hospitals | Masked | 15,985 | 4,000 |
| **Compliance Auditor** | `auditor_user` | All Hospitals | Unmasked via `pii_vault` | 15,985 | 4,000 |

---

## 5. Porting to Databricks Unity Catalog

1. **Upload Code**: Import the repository into Databricks Repos (`Workspaces -> Repos`).
2. **Store Raw Data in UC Volume**: Upload `MediaSync_Source_Data` to a Unity Catalog Volume:
   `/Volumes/medisync_catalog/landing/source_data`
3. **Configure Secrets**: Create secret for deterministic hashing:
   ```bash
   databricks secrets create-scope medisync_secrets
   databricks secrets put-secret medisync_secrets medisync_salt --string-value "<YOUR_SALT>"
   ```
4. **Deploy Governance DDL**:
   Execute `sql/ddl.sql` and `sql/unity_catalog_policies.sql` in Databricks SQL Editor.
5. **Run Workflow Notebooks**:
   - `notebooks/01_bronze_ingestion.py`
   - `notebooks/02_profiling.py`
   - `notebooks/03_silver_quarantine.py`
   - `notebooks/04_gold.py`

---

## 6. Data Dictionary

### Reference Tables
| Table | Description | Primary Key | Key Attributes |
|---|---|---|---|
| `reference_hospitals` | Master list of network hospitals | `hospital_id` | `hospital_name`, `city`, `region`, `bed_capacity` |
| `reference_user_access` | User role and scope permissions | `user_name` | `role`, `hospital_id`, `region` |

### Bronze Tables (Raw, Append-Only)
| Table | Format | Business Key | Audit Metadata Columns |
|---|---|---|---|
| `bronze_patients` | Parquet / SQL | `patient_id` | `batch_id`, `source_file`, `ingest_timestamp` |
| `bronze_encounters` | Parquet / SQL | `encounter_id` | `batch_id`, `source_file`, `ingest_timestamp`, `primary_diagnosis_code` |
| `bronze_lab_results` | Parquet / SQL | `lab_result_id` | `batch_id`, `source_file`, `ingest_timestamp` |
| `bronze_claims` | Parquet / SQL | `claim_id` | `batch_id`, `source_file`, `ingest_timestamp` |

### Silver Tables (Standardized, Typed, Deduplicated, Masked)
| Table | Primary Key | Non-PII & Masked Columns | Derived Attributes |
|---|---|---|---|
| `silver_patients` | `patient_id` (tokenized) | `full_name` (R***), `phone` (******1234), `email` (u***@domain), `national_id` (********1234), `city`, `primary_hospital_id` | `age_band` (10-yr band), `patient_age` |
| `silver_encounters` | `encounter_id` | `patient_id` (tokenized), `hospital_id`, `department`, `encounter_type`, `admit_date` (ISO), `discharge_date` (ISO), `primary_diagnosis_code`, `attending_doctor_id` | `length_of_stay_days` |
| `silver_lab_results` | `lab_result_id` | `encounter_id`, `test_code`, `test_name`, `result_value`, `unit`, `reference_low`, `reference_high`, `result_date` | `lab_flag` (`normal` / `abnormal`) |
| `silver_claims` | `claim_id` | `encounter_id`, `insurer`, `claim_amount`, `approved_amount`, `claim_status` (`Approved`/`Pending`/`Rejected`), `claim_date` (ISO) | Cleaned financial status |

### Restricted PII Vault & Governance Tables
| Table | Description | Primary Key | Stored Fields |
|---|---|---|---|
| `pii_vault` | Secure original PII repository | `patient_id_token` | `original_patient_id`, `full_name`, `phone`, `email`, `national_id`, `date_of_birth`, `batch_id`, `created_at` |
| `quarantine_records` | Rejection log with failure reasons | `quarantine_id` | `entity`, `business_key`, `reason` (`BAD_DATE_FORMAT`, `ORPHAN_FK`, `NULL_BUSINESS_KEY`), `record_payload`, `quarantine_timestamp` |
| `batch_audit` | Execution reconciliation log | `batch_id` × `started_at` | `rows_read`, `rows_loaded`, `rows_quarantined`, `rows_superseded`, `status`, `error_message` |

### Gold Analytics Tables
| Table | Business Grain | Metrics & Aggregations |
|---|---|---|
| `gold_hospital_daily_admissions` | `hospital_id` × `admission_date` | `admissions`, `unique_patients` |
| `gold_readmission_30d` | `hospital_id` × `discharge_month` | `discharges`, `readmissions_30d`, `readmission_rate` |
| `gold_claims_summary` | `hospital_id` × `claim_month` | `total_claims`, `total_claim_amount`, `avg_claim_amount`, `approved_claims`, `pending_claims`, `rejected_claims`, `approved_amount` |
| `gold_lab_abnormality` | `hospital_id` × `test_code` | `total_tests`, `abnormal_tests`, `abnormality_rate` |
