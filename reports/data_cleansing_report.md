# MediSync Health Network: Data Cleansing & Quality Transformation Report

**Generated At:** 2026-10-06T11:37:50Z  
**Pipeline Scope:** Full Multi-Batch Lakehouse Processing (`batch_0`, `batch_1`, `batch_2`)  
**Storage Architecture:** Medallion Ingestion (`Bronze` Raw $\to$ `Silver` Cleansed & Masked)  

---

## 1. Executive Summary & Lakehouse Volume Reconciliation

The MediSync automated data platform processes raw hospital extracts across four disparate formats (CSV, JSONL, Parquet, Excel), standardizes data types, removes duplicates, validates foreign keys, masks patient identifiers, and isolates defective rows into quarantine.

The pipeline strictly guarantees the **Fundamental Lakehouse Invariant**:
$$\mathbf{Bronze\_Rows} = \mathbf{Silver\_Loaded} + \mathbf{Quarantined\_Records} + \mathbf{Superseded\_Records}$$

### Cumulative Volume Reconciliation Matrix
| Entity | Bronze (Raw Ingested) | Silver (Cleansed & Loaded) | Quarantined (Defective) | Superseded (Duplicates & Redeliveries) | Mathematical Verification |
|---|---|---|---|---|---|
| **Patients** | 4,800 | 4,400 | 0 | 400 | 4800 == 4400 + 0 + 400 (VERIFIED) |
| **Encounters** | 19,743 | 17,587 | 30 | 2,126 | 19743 == 17587 + 30 + 2126 (VERIFIED) |
| **Lab Results** | 30,708 | 30,398 | 30 | 280 | 30708 == 30398 + 30 + 280 (VERIFIED) |
| **Claims** | 13,249 | 12,309 | 21 | 919 | 13249 == 12309 + 21 + 919 (VERIFIED) |
| **TOTAL NETWORK** | **68,500** | **64,694** | **81** | **3,725** | **100.0% Exact Reconciliation** |

---

## 2. Before vs. After Cleansing Transformation Breakdown

### 2.1 Patients Entity (`patients`)
| Dimension / Attribute | Before Cleansing (Bronze Layer) | After Cleansing (Silver Layer) | Remediation Applied |
|---|---|---|---|
| **Natural Identifiers (`patient_id`)** | Plaintext cleartext IDs (e.g. `P000001`, `P000002`) | Cryptographic salted tokens (e.g. `9b7ce10c...`) | Replaced with deterministic SHA-256 + secret salt; raw key decoupled into `pii_vault`. |
| **Full Names (`full_name`)** | Plaintext names, mixed casing, extra spacing (e.g. ` Yash  Joshi `) | Standardized Title Case, masked format (`Y***`) | Extraneous spaces removed, casing standardized, direct PII masked with initial + asterisks. |
| **Gender Coding (`gender`)** | **13 messy variations**: `F, FEMALE, Female, M, MALE, Male, O, Other...` | **4 canonical codes**: `F, M, O, U` | Case-insensitive regex mapped `MALE/Male/m` $\to$ `M`, `FEMALE/Female/f` $\to$ `F`, `OTHER/Other` $\to$ `O`, invalid/null $\to$ `U`. |
| **Date of Birth (`date_of_birth`)** | 8 conflicting date formats (`DD/MM/YYYY`, `MM-DD-YYYY`, etc.); 40.7% non-ISO | **Removed from Silver**; derived `patient_age` & `age_band` (`10-19`, `20-29`, etc.) | Direct DOB decoupled to prevent age re-identification; age bands derived for analytical safety. |
| **Phone Numbers (`phone`)** | 68.6% unstandardized with hyphens, spaces, and brackets | 100% masked: `******` + last 4 digits (e.g. `******3210`) | Non-digits stripped, length validated, masked for privacy compliance. |
| **Email Addresses (`email`)** | Plaintext emails with 211 invalid formatting errors | Masked with initial + domain (e.g. `y***@example.com`) | RFC-compliant regex validation; invalid strings masked or isolated. |
| **Deduplication (`last_updated`)** | 4,800 records across batches with repeat entries | **4,400 unique patients** (latest state) | Intra-batch and high-watermark deduplication keeps `max(last_updated)`; 400 older versions marked superseded. |

---

### 2.2 Insurance Claims Entity (`claims`)
| Dimension / Attribute | Before Cleansing (Bronze Layer) | After Cleansing (Silver Layer) | Remediation Applied |
|---|---|---|---|
| **Health Insurers / Payers (`insurer`)** | **24 noisy variations** (`Star-Health`, `STAR HEALTH `, `Care Health Insurance`, `Niva-Bupa`, etc.) | **Exactly 6 canonical payers**: `Bajaj Allianz, Care Health, HDFC ERGO, ICICI Lombard, Niva Bupa, Star Health` | Standardized canonical mapping dictionary mapped all 24 spelling variants into primary insurers. |
| **Adjudication Status (`claim_status`)** | Inconsistent casing & substrings (`APPROV`, `PEND`, `REJECT`, `Approved`) | **3 standard statuses**: `Approved`, `Pending`, `Rejected` | Normalization parser categorized claim statuses deterministically. |
| **Financial Currency Amounts** | Numeric strings with varying decimals in raw Excel | Standardized float currency with 2 decimal places | Typed to numeric float; nulls handled gracefully. |
| **Foreign Key Integrity** | Claims referencing non-existent encounters | **21 orphan claims quarantined** | Orphan claims routed to `quarantine_records` (`ORPHAN_FK`), ensuring zero unlinked financial records in Silver. |
| **Re-Delivered Batch Files** | Redelivered Day 2 claims file in Batch 2 (867 rows) | **0 duplicate claims loaded** | High-watermark timestamp comparison detected matching or older `last_updated`, skipping all 863 duplicate rows. |

---

### 2.3 Hospital Encounters Entity (`encounters`)
| Dimension / Attribute | Before Cleansing (Bronze Layer) | After Cleansing (Silver Layer) | Remediation Applied |
|---|---|---|---|
| **Admit & Discharge Dates** | 40.4% non-ISO date formats (`DD-MM-YYYY`, `YYYY/MM/DD`, etc.) | **100.0% ISO-8601 (`YYYY-MM-DD`)** | Multi-format date engine normalized all valid dates; unparseable strings quarantined. |
| **Length of Stay (`length_of_stay_days`)** | Not calculated; missing in raw EHR extracts | **Derived integer days** ($discharge - admit$) | Automated delta calculation with `pd.isna()` safety guards preventing null string crashes. |
| **Encounter Type** | Inconsistent text (`inpatient`, `Inpatient`, `outpatient`, `Emergency`) | Standardized Title Case categories | Normalized to `Inpatient`, `Outpatient`, `Emergency`; enables proper hospital admission filtering in Gold. |
| **Foreign Key Integrity** | Encounters referencing unregistered patient IDs | **30 orphan encounters quarantined** | Encounters without valid patient keys routed to `quarantine_records` (`ORPHAN_FK`). |

---

### 2.4 Laboratory Diagnostic Results (`lab_results`)
| Dimension / Attribute | Before Cleansing (Bronze Layer) | After Cleansing (Silver Layer) | Remediation Applied |
|---|---|---|---|
| **Result Dates (`result_date`)** | Mixed text timestamps and date strings | **100.0% ISO-8601 (`YYYY-MM-DD`)** | Extracted and normalized to calendar day ISO representation. |
| **Diagnostic Test Names & Codes** | Irregular casing and extra whitespace (` glucose `, `GLUCOSE`) | **Uppercase standardized** (`GLUCOSE`, `CHOL`, `CREAT`, etc.) | Whitespace collapsed, strings uppercase-normalized. |
| **Clinical Abnormality (`lab_flag`)** | Missing categorical flags in raw analyzers | **Derived clinical flag**: `normal` vs `abnormal` | Automated clinical evaluation checking result value against `reference_low` and `reference_high`. |
| **Foreign Key Integrity** | Lab tests referencing invalid encounters | **30 orphan lab results quarantined** | Orphan lab results routed to `quarantine_records` (`ORPHAN_FK`). |

---

## 3. Data Quality Quarantine Analysis

A total of **81 defective records** were caught by the data quality firewall and diverted to `quarantine_records`:

| Entity | Quarantined Count | Primary Failure Reason | Defect Description |
|---|---|---|---|
| **Encounters** | 30 | `ORPHAN_FK` | `patient_id` not found in valid Silver patients table |
| **Lab Results** | 30 | `ORPHAN_FK` | `encounter_id` not found in valid Silver encounters table |
| **Claims** | 21 | `ORPHAN_FK` | `encounter_id` not found in valid Silver encounters table |
| **Patients** | 0 | `N/A` | All patient hospital references validated against `hospitals.csv` |
| **TOTAL** | **81** | `ORPHAN_FK` | **100% of defective relationships quarantined without lake pollution** |

---

## 4. Privacy & Governance Verification

- **PII Absence in Silver & Gold**: Direct identifiers (`full_name`, `phone`, `email`, `national_id`, `date_of_birth`) are completely absent or irreversibly masked in Silver, and 100% absent in Gold.
- **Fail-Fast Dashboard Assertion**: Verified that the Streamlit leadership dashboard fails fast if any PII column ever appears.
- **Cryptographic Decoupling**: Tokenized `patient_id` values cannot be reversed without access to both `pii_vault` and the secure `MEDISYNC_SALT`.
