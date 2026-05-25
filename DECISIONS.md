# Decisions

## SAP: flat file over IDoc/OData

**Choice:** Tab-delimited flat file export from SE16N or a custom ABAP report (MM60-style material movement report).

**Why:** The PM said the client has fuel data "sitting in SAP." In practice, sustainability teams rarely have direct OData API access — that requires Basis/ABAP coordination and is unusual for a new client. What they actually get is a dump from IT: a tab-delimited or semicolon-delimited text file that looks like a spreadsheet. IDoc XML is technically richer but is a B2B integration format, not an analyst-facing export. BAPI calls require an RFC connection which a prototype doesn't have.

The flat file approach is the right call for analyst self-service: the facilities/sustainability lead can export it themselves from SAP with no IT involvement.

**What I'd ask the PM:** Does the client's SAP team have an OData service already exposed for sustainability reporting? If so, the parser architecture (yielding normalized rows) is identical — we just swap the ingestion mechanism.

**What subset of SAP I'm handling:**
- Movement types 201 (GI to cost center), 261 (GI to production order), 551, 601 — consumption movements only
- Materials with fuel keywords in the description (diesel, Heizöl, natural gas, LPG, petrol)
- Plants identified by WERKS code, with a static lookup table for display names

**What I'm ignoring:**
- BAPI/RFC live pulls
- IDoc XML format
- Multi-level BOM explosions for procurement (raw materials → fuel equivalent)
- FI direct postings that bypass MM
- Batch/lot tracking

---

## Utility: portal CSV over Green Button XML

**Choice:** Standard portal CSV export — one row per billing period per meter.

**Why:** Green Button XML is a US standard theoretically available for commercial accounts via ESPI (Energy Services Provider Interface). In practice: most UK/EU utilities (which this client has — Frankfurt, London facilities) don't implement Green Button. Even US utilities that offer it require account-level enrollment that enterprise facilities teams often haven't done. The portal CSV is what every utility portal actually gives you: download → CSV → done.

I specifically chose not to handle PDF bills. PDFs require OCR, have no standard schema, and produce high error rates. Defensible to a client that the PDF route needs a dedicated extraction pipeline.

**What I'm handling:**
- kWh or MWh per billing period per meter
- Period start/end as actual read dates (not calendar months)
- Estimated vs actual reads (flagged as a quality warning)
- Multiple meters per account

**What I'd ask the PM:** Do any facilities use half-hourly (HH) interval data from smart meters? That's a fundamentally different ingestion path (48 readings/day/meter) and would need separate handling.

**What I'm ignoring:**
- TOU (time-of-use) tariff breakdowns
- Reactive power / kVAR readings
- Gas meters (separate Scope 1 calculation)
- Market-based vs location-based Scope 2 (currently using DEFRA UK grid average; market-based requires supplier-specific factors)

---

## Travel: Concur CSV export over API

**Choice:** Concur standard expense report CSV export.

**Why:** Navan and Concur both expose REST APIs, but they require OAuth configuration specific to each client's instance. For a new client onboarding, getting API credentials takes time. The CSV export is available immediately — the travel manager downloads it from the Concur admin console under Reports. The schema is consistent enough across clients that a single parser handles both Concur and Navan exports.

**Distance calculation:** Concur records transactions, not distances. I calculate great-circle (haversine) distance from IATA airport codes for flights and some ground transport. The lookup table covers 70 major global hubs. Routes through smaller airports fall back to "distance unknown" with a quality flag.

**What I'm handling:**
- AIR: distance from IATA pairs, emission factor by class (economy/business/first) and haul (short <3700km / long)
- HOTEL: nights × emission factor (GHG Protocol Scope 3 Standard value of 31.4 kg CO2e/room-night)
- CAR_RENTAL, TAXI, RAIL: distance × emission factor (DEFRA 2023)
- Flexible header mapping to handle Concur variants and Navan exports

**What I'd ask the PM:** Does the client use Concur Travel (flight bookings tracked at time of booking) or only Concur Expense (reimbursement submissions)? Travel-booked flights have more complete routing data than expense-submitted ones.

**What I'm ignoring:**
- Rail routes between specific city pairs (requires a rail distance API)
- Hotel emission factor variation by country or star rating
- Taxi/rideshare without a distance value (cost-based estimation could work but introduces significant uncertainty)
- Mileage claims from personal vehicles

---

## Review workflow: simple status machine

**Choice:** Four statuses — PENDING → APPROVED / REJECTED / FLAGGED. APPROVED records can be locked.

**Why:** The PM's requirement is "let analysts review and sign off before it goes to auditors." That's a single-step approval, not a multi-stage workflow. Adding stages (e.g., "sent for clarification," "awaiting client confirmation") before we understand the actual workflow would be premature. The flagging mechanism provides a way to call out records that need attention without rejecting them outright.

**What I'd ask the PM:** Is there a second-level sign-off before audit, or does the analyst's approval go directly to the auditor? If there's a CFO or Head of Sustainability sign-off, we'd need a second review tier.

---

## Emission factors: DEFRA 2023 + ICAO 2023

**Choice:** DEFRA UK GHG Conversion Factors 2023 for fuels and electricity, ICAO 2023 for aviation, GHG Protocol Scope 3 Standard for hotels.

**Why:** DEFRA is the authoritative UK source and is commonly used for international reporting as a default. The client has European operations (Frankfurt, London). EPA eGRID would be more accurate for US electricity, but using a single consistent source is defensible for a prototype. The model supports multiple EF versions (valid_from/valid_to) so we can add regional factors later.

**What I'd ask the PM:** What reporting standard is the client using — GHG Protocol, ISO 14064, CDP? GHG Protocol allows market-based Scope 2 (using supplier EF) which would change the electricity calculation significantly.

---

## Authentication: none in the prototype

See TRADEOFFS.md.

---

## SQLite in development, PostgreSQL in production

SQLite is the default for local development (no setup needed). The `DATABASE_URL` environment variable switches to PostgreSQL on Railway. Django's ORM is the same for both; migrations run without changes.

---

## Billing period preservation

A utility billing period of 2024-01-03 to 2024-02-05 is stored as-is, not snapped to January or February. Snapping introduces either double-counting or a gap. The reporting layer (if built) would be responsible for pro-rating across calendar months. This matches what the GHG Protocol recommends: report data as received, explain methodology.
