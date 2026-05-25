# Sources — Research Behind Each Data Source

## 1. SAP Fuel & Procurement

### What I researched

SAP has four realistic export mechanisms for sustainability data:
- **IDoc (Intermediate Document):** XML/flat-file format used for B2B EDI integrations. Requires ABAP configuration and is not analyst-facing.
- **OData service (via S/4HANA or SAP Gateway):** RESTful API with structured JSON. Available in newer S/4HANA environments but uncommon for sustainability teams without IT enablement.
- **BAPI:** Remote Function Calls, programmatic access. Requires RFC connection.
- **Flat file via SE16N / custom report:** The analyst or IT dumps a table or custom ABAP report to a text file. This is what sustainability teams actually use in practice.

The relevant SAP transaction for fuel/material consumption is **MM60** (Inventory Turnover Report) or a custom ABAP report off table **MSEG** (Material Document Segment). Fields include WERKS (plant), MATNR (material), MENGE (quantity), MEINS (unit of measure), BUDAT (posting date), BWART (movement type).

German column headers appear in SAP systems configured for German locale (most European SAP instances). MENGE/MEINS/WERKS/BUDAT are universal field names but the display headers vary by language setting.

### What my sample data looks like and why

`sap_fuel_mm60.txt` simulates an MM60 export from a multinational client with two German plants (DE01, DE02), two US plants (US01, US02), and a UK office (GB01). Intentional design choices:
- German headers (WERKS, MATNR, MAKTX, etc.)
- Mix of units: L for European plants, GAL (US gallons) for US plants, M3 and CCF for natural gas
- Mix of date formats: `DD.MM.YYYY` for German plants, `MM/DD/YYYY` for US plants
- Movement types 201 and 261 (both consumption)
- One row with a negative quantity (a correction posting — realistic, triggers a quality flag)
- Non-fuel material (cardboard packaging) to test that the parser correctly classifies it as Scope 3

### What would break in a real deployment

- **Plant codes without a lookup table:** Our `PLANT_NAMES` dict covers 6 plants. A real client has 50–300 plants. The parser passes through unknown plant codes without a display name — analysts see `US02` instead of `Houston Plant`. We'd need to ingest the plant master data (SAP table T001W) separately.
- **Material numbers without descriptions:** If MAKTX is blank, fuel type detection fails. Real SAP exports sometimes export material numbers but not descriptions in truncated formats.
- **SAP UoM edge cases:** SAP has ~200 standard UoM codes. Our mapping covers the 10 most common for fuels. `BBL` (barrels), `LBS`, `OZ`, and petroleum-industry units would be encountered at oil/gas clients.
- **Financial postings bypassing MM:** Some fuel costs are booked directly in FI (Finance) via journal entries (transaction FB50), not through MM goods movements. These would not appear in an MM60 export at all.
- **Reversals:** SAP reversal movements (movement type 102, 262) appear as negative quantities. We flag negative quantities but don't automatically pair them with the original movement for net calculation.

---

## 2. Utility Electricity

### What I researched

Facilities teams typically access electricity data through one of:
- **Utility portal CSV export:** Available on most commercial portals (E.ON, EDF, British Gas, ComEd, etc.). Standard columns: account number, meter ID, billing period, kWh, peak demand, tariff code.
- **Green Button XML/JSON:** A US standard (ESPI) for sharing interval data. Theoretically available for commercial accounts but enrollment rates are low.
- **PDF bills:** Structured but not parseable without OCR. Avoided.
- **Half-hourly (HH) data:** Smart meters export 48 readings per day. A completely different format and ingestion path — not handled.

The key insight I found in research: **billing periods do not align with calendar months**. A meter read happens when the utility technician visits or when a smart meter transmits. For large industrial accounts, reads are often contractually scheduled (e.g., always within 3 business days of the 1st). But in practice, periods of 28–35 days are normal, and a period straddling month boundaries by 5 days is common.

For UK accounts, meters are identified by **MPAN** (Meter Point Administration Number, 21 digits). For US, by **account number + service address**. Our `meter_id` field handles both.

### What my sample data looks like and why

`utility_portal.csv` covers three months of data for five meters across four facilities. Intentional choices:
- Billing periods that don't align with month boundaries (e.g., Jan 3 → Feb 1)
- One estimated read (ACC-001235 February) — triggers a quality warning
- Multiple meters per facility (Frankfurt main production + HVAC circuit)
- MWh values not included, but the parser handles them
- US and UK tariff codes mixed to show the parser is format-agnostic

### What would break in a real deployment

- **Market-based Scope 2:** For GHG Protocol market-based accounting, the emission factor is the supplier's specific factor (from a Renewable Energy Certificate or Power Purchase Agreement), not the grid average. Our current implementation uses the DEFRA UK grid average (0.207 kg CO2e/kWh) for all electricity. A client with PPAs or REGOs would need supplier-specific factors loaded per account.
- **Non-UK electricity:** We use the UK grid factor universally. The Houston plant (US) should use EPA eGRID ERCOT (0.386 kg CO2e/kWh), Frankfurt should use the German grid mix. We'd need a country/region lookup on the facility.
- **Reactive power charges:** Present in industrial exports, irrelevant to emissions, but confuses parsers that try to sum numeric columns.
- **Multi-fuel meters:** Some accounts include gas on the same export — different units (therms, kWh thermal), different scope.

---

## 3. Corporate Travel

### What I researched

Dominant platforms are Concur (SAP SE subsidiary, ~55% enterprise market share) and Navan (formerly TripActions, growing rapidly). Both expose:
- **Standard expense report CSV** (what we use): available to travel managers without API access
- **REST API with OAuth2**: Concur uses OAuth 2.0 with client credentials; Navan has a similar pattern. Both require per-client app registration.

The Concur standard expense export CSV (accessed via Reports > Expense Detail) contains transaction-level data: date, employee, expense type, vendor, amount, currency, and optional travel-specific fields (origin, destination, class of travel, hotel nights).

Key gap discovered in research: **Concur records expenses, not itineraries.** A business trip produces multiple rows: one AIR row, one HOTEL row per stay, one TAXI row. Distance is not always present — it appears only if the employee filled in a mileage field in the expense form, or if Concur's travel booking module populated it. For flights booked outside the corporate travel platform, only origin/destination airport codes may be present (from the airline receipt).

For distance calculation from IATA codes, I use the **haversine great-circle formula** — the shortest path between two points on a sphere. This understates actual flight distances by ~5–8% (flights follow airways, not great circles, especially at high latitudes). ICAO's methodology uses the same approach as a simplification.

Emission factors for aviation include a **Radiative Forcing Index (RFI) multiplier of ~1.9** because aircraft contrails and NOx emissions at altitude have a warming effect beyond just CO2. The ICAO and DEFRA factors I use include this.

### What my sample data looks like and why

`travel_concur.csv` covers Q1 2024 travel for 8 employees across a multinational client. Intentional choices:
- Missing `Distance_KM` for flights (realistic — Concur doesn't auto-populate) to test IATA-based calculation
- Mix of classes (Economy and Business) to test emission factor multipliers
- Short-haul and long-haul routes crossing the 3700km threshold
- Hotel rows without nights count (row defaults to 1 night with a quality flag)
- Taxi with a provided distance (some clients configure this)
- Row using `AIRFARE` and `CAR RENTAL` (space-separated) as alternative expense type names to test flexible header mapping
- One employee (Marcus Weber) traveling multiple times with Business class — realistic for senior executive travel

### What would break in a real deployment

- **IATA codes not in lookup table:** Our lookup covers 70 airports. A flight between two regional airports (e.g., Bristol BRS to Southampton SOU) would produce "distance unknown." We'd need a complete IATA database (~10,000 entries) or a geocoding API.
- **Multi-leg itineraries:** A flight from London to Singapore via Dubai is recorded as two separate expense rows, but our distance is calculated direct LHR→SIN. This underestimates the actual distance.
- **Rail distances without station pairs:** We use a provided distance or skip rail rows without one. A full implementation would need a rail distance matrix or API.
- **Personal vehicle mileage:** Employees submitting mileage claims in Concur appear as a dollar amount with a vehicle type note, not a distance. We'd need to parse the reimbursement rate to back-calculate distance (e.g., HMRC rate of £0.45/mile in the UK).
- **Currency conversion for cost-based emission estimation:** Currently unused, but if we needed cost-based Scope 3 for non-travel procurement (e.g., spend data), USD/GBP/EUR conversion would be needed.
