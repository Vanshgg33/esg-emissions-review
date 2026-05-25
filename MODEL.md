# Data Model

## Core entities and why they exist

### Tenant
Single-column slug plus name. Every other entity has a `tenant` FK. Row-level isolation chosen over Postgres schema-per-tenant because this is a prototype shared by a small number of enterprise clients — schema-per-tenant adds significant migration overhead without proportional benefit at this scale. A production system with 100+ tenants would warrant revisiting.

### EmissionFactor
Versioned, with `valid_from` / `valid_to`. The important property is that changing this table does **not** silently alter historical records — the factor value is denormalized onto `NormalizedRecord` at ingest time. The EF row is provenance, not the source of truth for past calculations. This means an auditor can always reproduce a record's CO2e from the snapshot on the record itself.

```
EmissionFactor
  category        VARCHAR      e.g. 'diesel', 'electricity', 'air_economy_long'
  subcategory     VARCHAR      e.g. 'business_class'
  activity_unit   VARCHAR      the unit this factor denominates (L, kWh, km, nights)
  kg_co2e_per_unit DECIMAL(12,6)
  source          VARCHAR      full citation: 'DEFRA 2023 v1.0', 'ICAO 2023'
  valid_from      DATE
  valid_to        DATE (null)  null = currently active
```

### DataIngestion
One row per upload/pull event. Preserves the original file and a structured `processing_log` (JSON array of `{level, row, message}`) so the UI can show the analyst exactly which rows failed and why, without them having to re-parse the file.

```
DataIngestion
  tenant          FK(Tenant)
  source_type     ENUM         SAP_FUEL | UTILITY_ELEC | TRAVEL
  status          ENUM         PENDING | PROCESSING | COMPLETE | FAILED
  ingested_at     DATETIME
  ingested_by     VARCHAR      email/name of the analyst who triggered the upload
  raw_file        FILE         the original file, stored permanently
  original_filename VARCHAR
  row_count       INT
  error_count     INT
  warning_count   INT
  processing_log  JSON         [{level, row, message}, ...]
```

### RawRecord
**Immutable.** One row per source data row, created at parse time and never modified. `raw_data` stores the original key-value pairs exactly as received — before any normalization, unit conversion, or classification. This is the authoritative answer to "what did the client actually send us?"

If parsers change, or if a dispute arises, the raw record is the ground truth. Analysts can see it in the review drawer.

```
RawRecord
  ingestion       FK(DataIngestion)
  row_number      INT           the row number in the source file
  raw_data        JSON          {column_name: original_value, ...}
  parse_status    ENUM          OK | WARNING | ERROR
  parse_errors    JSON          [error_string, ...]
```

### NormalizedRecord
The canonical emissions record. This is what analysts review and what goes to auditors.

**Design invariants:**
1. `scope + category` together determine the emission calculation method. The scope is derived from the source: SAP fuel → Scope 1, utility electricity → Scope 2, travel → Scope 3.
2. `activity_quantity / activity_unit` are in normalized units — **L** for liquid fuels, **kWh** for electricity, **km** for transport distance, **nights** for hotel stays. Raw values are preserved in `activity_quantity_raw / activity_unit_raw`.
3. `co2e_kg = activity_quantity × emission_factor_value`. Computed at write time, not recomputed on reads.
4. `emission_factor_value / _unit / _source` are a snapshot of the factor used at ingest time. The EmissionFactor table can be updated safely.
5. `period_start / period_end` are the actual dates from the source, **not** snapped to calendar months. A utility bill covering 2024-01-03 to 2024-02-05 stays that way. Calendar-month bucketing is a reporting concern, not a storage concern.
6. `is_locked = True` prevents all further edits (enforced in API). Once an analyst locks an approved record, it is frozen for audit.
7. `flags` is a JSON array of human-readable warning strings, populated at parse time. `is_suspicious` is a boolean flag set when any flag condition is critical enough to warrant extra scrutiny.

```
NormalizedRecord
  tenant              FK(Tenant)
  source_record       OneToOne(RawRecord)    preserves the link to raw data
  scope               INT                    1 | 2 | 3
  category            ENUM                   stationary_combustion | purchased_electricity |
                                              business_travel_air | business_travel_hotel |
                                              business_travel_ground | purchased_goods
  facility_id         VARCHAR                SAP plant code / meter MPAN / employee ID
  facility_name       VARCHAR                human-readable location
  description         VARCHAR                free-form description from source
  period_start        DATE
  period_end          DATE
  activity_quantity_raw  DECIMAL(18,4)       as received
  activity_unit_raw      VARCHAR             as received (e.g. 'GAL', 'MENGE')
  activity_quantity      DECIMAL(18,4)       normalized
  activity_unit          VARCHAR             normalized ('L', 'kWh', 'km', 'nights')
  emission_factor_value  DECIMAL(12,6)       snapshot at ingest time
  emission_factor_unit   VARCHAR             e.g. 'kg CO2e/L'
  emission_factor_source VARCHAR             citation
  co2e_kg             DECIMAL(18,4)
  review_status       ENUM                   PENDING | APPROVED | REJECTED | FLAGGED
  reviewed_by         VARCHAR
  reviewed_at         DATETIME
  review_notes        TEXT
  is_locked           BOOL
  locked_at           DATETIME
  locked_by           VARCHAR
  flags               JSON                   [warning_string, ...]
  is_suspicious       BOOL
  created_at          DATETIME
  updated_at          DATETIME
```

### AuditEvent
Append-only event log. Never updated, never deleted.

Every state change on a `NormalizedRecord` or `DataIngestion` creates one of these. `before_state` and `after_state` are JSON snapshots of the changed fields, so the full history of a record can be reconstructed without relying on the record's current state.

```
AuditEvent
  tenant          FK(Tenant)
  record          FK(NormalizedRecord, null)  null for ingestion-level events
  ingestion       FK(DataIngestion, null)
  event_type      ENUM         INGESTION_STARTED | INGESTION_COMPLETE | INGESTION_FAILED |
                               RECORD_CREATED | RECORD_REVIEWED | RECORD_FLAGGED |
                               RECORD_LOCKED | RECORD_EDITED | BULK_REVIEW
  actor           VARCHAR      who triggered the event
  timestamp       DATETIME     auto-set, never editable
  before_state    JSON
  after_state     JSON
  note            TEXT
```

## Scope classification

| Source | Scope | Category |
|---|---|---|
| SAP fuel (diesel, petrol, heating oil, LPG, natural gas) | 1 | stationary_combustion or mobile_combustion |
| SAP non-fuel materials | 3 | purchased_goods |
| Utility electricity | 2 | purchased_electricity |
| Travel — flights | 3 | business_travel_air |
| Travel — hotel | 3 | business_travel_hotel |
| Travel — car rental, taxi, rail | 3 | business_travel_ground |

## Unit normalization

| Source unit | Normalized unit | Factor |
|---|---|---|
| L, LT (SAP) | L | 1 |
| GAL (US gallon) | L | × 3.78541 |
| GLI (UK gallon) | L | × 4.54609 |
| KG (liquid fuel) | L | ÷ density (0.845 diesel, 0.729 petrol) |
| TO (metric ton) | KG → L | × 1000 ÷ density |
| CF (cubic feet) | M3 | × 0.028317 |
| CCF | M3 | × 2.83168 |
| MWh | kWh | × 1000 |
| Distance (provided) | km | pass-through |
| Distance (IATA calculated) | km | haversine great-circle |

## Multi-tenancy

Every query in the API filters by `tenant_id`. The UI passes `tenant_id` as a query parameter on all requests. The backend does not enforce authentication beyond this — that is an explicit tradeoff (see TRADEOFFS.md).

## Audit trail completeness

Every operation that changes a `NormalizedRecord` review state calls `AuditEvent.objects.create(...)` in the same transaction. The API layer returns 409 if `is_locked=True` rather than silently ignoring the edit. These two together ensure:
1. The audit trail is complete for all changes that succeeded.
2. Locked records cannot be silently altered.
