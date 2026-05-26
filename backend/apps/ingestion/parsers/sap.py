"""
SAP flat-file parser for fuel and procurement data.

Format choice: MM60 / MB52 style consumption report exported as tab-delimited text
via SAP transaction SE16N or a custom ABAP report. This is the most common export
mechanism for sustainability teams who don't have direct OData access — they get a
dump from IT that looks like a spreadsheet.

Real-world complications handled here:
- German column headers (WERKS, MENGE, MEINS) alongside English (Plant, Quantity, UoM)
- SAP UoM codes that are not ISO: L, KG, GAL, M3, CF, MBT, and their SAP-internal
  variants (e.g. 'LT' for liter in some configurations)
- Date in five common SAP formats: DD.MM.YYYY (German locale), YYYYMMDD (IDoc),
  MM/DD/YYYY (US plant locale), YYYY/MM/DD, DD-MM-YYYY, YYYY.MM.DD
- Plant codes (WERKS) that are opaque strings like 'DE01', 'US02' — we pass them
  through and let the facility lookup table in PLANT_NAMES do display name mapping
- Movement types: we only want goods-issue movements (consumption), not goods-receipt.
  Types 201 (GI to cost center), 261 (GI to production order), 551 (scrapping) are
  consumption. Types 101/501 (GR) are receipts and are excluded.
- Materials: we detect fuel vs. non-fuel by material description keywords. This is
  imperfect in the real world but representative.

What we are NOT handling (documented in DECISIONS.md):
- IDoc XML format (chosen flat-file instead for analyst self-service)
- BAPI/OData live pull (no SAP system available for prototype)
- Multi-currency procurement (only fuel quantity matters for Scope 1; cost is not used)
- Materials with no movement type (direct FI postings)
"""

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator

from .normalizer import build_header_map, to_canonical_row

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Column header normalisation
# ---------------------------------------------------------------------------

# Map canonical field name → all known aliases (German + English + common variants)
_COLUMN_ALIASES: dict[str, list[str]] = {
    'plant':        ['WERKS', 'Plant', 'Werk', 'plant'],
    'material':     ['MATNR', 'Material', 'Material Number', 'Materialnummer', 'material'],
    'description':  ['MAKTX', 'Material Description', 'Materialbezeichnung', 'Materialkurztext', 'desc'],
    'post_date':    ['BUDAT', 'Posting Date', 'Buchungsdatum', 'Belegdatum', 'Date', 'post_date'],
    'quantity':     ['MENGE', 'Quantity', 'Menge', 'qty', 'quantity'],
    'unit':         ['MEINS', 'UoM', 'Unit', 'Einheit', 'ME', 'unit'],
    'movement':     ['BWART', 'Movement Type', 'Bewegungsart', 'MvT', 'movement'],
    'cost_center':  ['KOSTL', 'Cost Center', 'Kostenstelle', 'cost_center'],
    'plant_name':   ['ANLZL', 'Plant Name', 'Werksname', 'plant_name'],
}

# Movement types that represent consumption (goods-issue)
_CONSUMPTION_MOVEMENTS = {'201', '261', '551', '601', '621', '643'}

# SAP UoM → (standard_unit, conversion_factor_to_standard)
# standard units: L for liquid, M3 for gas, KWH for electricity
_UOM_TO_STANDARD: dict[str, tuple[str, Decimal]] = {
    'L':    ('L',   Decimal('1')),
    'LT':   ('L',   Decimal('1')),
    'GAL':  ('L',   Decimal('3.78541')),   # US gallon
    'GLL':  ('L',   Decimal('3.78541')),   # SAP variant for US gallon
    'GLI':  ('L',   Decimal('4.54609')),   # UK (imperial) gallon
    'KG':   ('KG',  Decimal('1')),         # density applied in caller
    'G':    ('KG',  Decimal('0.001')),
    'TO':   ('KG',  Decimal('1000')),      # metric ton (SAP internal)
    'TON':  ('KG',  Decimal('1000')),      # metric ton (common alias)
    'MT':   ('KG',  Decimal('1000')),      # metric ton (ISO alias)
    'M3':   ('M3',  Decimal('1')),
    'CF':   ('M3',  Decimal('0.028317')),  # cubic feet
    'CCF':  ('M3',  Decimal('2.83168')),   # hundred cubic feet
    'MBT':  ('M3',  Decimal('28.3168')),   # thousand cubic feet (MMBTU proxy for gas)
}

# Material keyword → fuel type (used to classify Scope 1 fuel vs other materials)
_FUEL_KEYWORDS: dict[str, str] = {
    'diesel':       'diesel',
    'heizöl':       'heating_oil',
    'heizoel':      'heating_oil',
    'fuel oil':     'heating_oil',
    'petrol':       'petrol',
    'benzin':       'petrol',
    'gasoline':     'petrol',
    'natural gas':  'natural_gas',
    'erdgas':       'natural_gas',
    'lpg':          'lpg',
    'flüssiggas':   'lpg',
}

# Density (kg/L) for liquid fuels — used when source unit is KG
_FUEL_DENSITY: dict[str, Decimal] = {
    'diesel':      Decimal('0.845'),
    'heating_oil': Decimal('0.845'),
    'petrol':      Decimal('0.729'),
    'lpg':         Decimal('0.510'),
}

PLANT_NAMES: dict[str, str] = {
    'DE01': 'Frankfurt Manufacturing',
    'DE02': 'Munich Warehouse',
    'US01': 'Chicago Facility',
    'US02': 'Houston Plant',
    'GB01': 'London Office',
    'SG01': 'Singapore Hub',
}


@dataclass
class SapParseResult:
    row_number: int
    raw_data: dict
    post_date: date | None = None
    plant: str = ''
    material: str = ''
    description: str = ''
    fuel_type: str = ''
    quantity_raw: Decimal = Decimal('0')
    unit_raw: str = ''
    quantity_normalized: Decimal = Decimal('0')
    unit_normalized: str = ''
    cost_center: str = ''
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)  # analyst-review flags (row ingested but needs sign-off)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0



def _parse_sap_date(raw: str) -> date:
    for fmt in ('%d.%m.%Y', '%Y%m%d', '%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y',
                '%Y/%m/%d', '%d-%m-%Y', '%Y.%m.%d'):
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: '{raw}'")


def _detect_fuel_type(description: str) -> str:
    desc_lower = description.lower()
    for keyword, fuel_type in _FUEL_KEYWORDS.items():
        if keyword in desc_lower:
            return fuel_type
    return ''


def _normalize_quantity(quantity: Decimal, raw_unit: str, fuel_type: str) -> tuple[Decimal, str]:
    """
    Convert raw quantity + SAP UoM to standard unit.
    Returns (normalized_quantity, standard_unit).
    KG → L requires fuel density; if density unknown, returns KG.
    """
    uom = raw_unit.strip().upper()
    if uom not in _UOM_TO_STANDARD:
        return quantity, raw_unit   # pass through unknown units for analyst to inspect

    standard_unit, factor = _UOM_TO_STANDARD[uom]
    converted = quantity * factor

    if standard_unit == 'KG' and fuel_type in _FUEL_DENSITY:
        # Convert mass → volume for liquid fuels
        return converted / _FUEL_DENSITY[fuel_type], 'L'

    return converted, standard_unit


def _detect_delimiter(sample: str) -> str:
    """Pick the most likely delimiter from tab, semicolon, comma."""
    counts = {'\t': sample.count('\t'), ';': sample.count(';'), ',': sample.count(',')}
    return max(counts, key=counts.get)


def parse(file_content: str | bytes) -> Iterator[SapParseResult]:
    """
    Parse a SAP flat-file export. Yields one SapParseResult per data row.
    Handles tab-delimited, semicolon-delimited, and comma-delimited exports.
    Skips header-only rows, SAP summary footer lines, and blank rows.
    """
    if isinstance(file_content, bytes):
        # SAP often exports in CP1252 (Windows Latin-1); fall back to latin-1
        for encoding in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                file_content = file_content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

    # Strip BOM that survives when content arrives as a pre-decoded str
    file_content = file_content.lstrip('\ufeff')

    sample = file_content[:2000]
    delimiter = _detect_delimiter(sample)
    logger.debug("SAP parser: detected delimiter=%r", delimiter)

    reader = csv.DictReader(io.StringIO(file_content), delimiter=delimiter)

    if reader.fieldnames is None:
        logger.warning("SAP parser: no fieldnames found — empty file?")
        return

    logger.debug("SAP parser: raw fieldnames=%r", reader.fieldnames)

    header_map = build_header_map(list(reader.fieldnames), _COLUMN_ALIASES)

    logger.debug("SAP parser: resolved header_map=%r", header_map)
    if not header_map:
        logger.error(
            "SAP parser: zero headers resolved — delimiter mismatch or unrecognised headers. "
            "raw fieldnames: %r", reader.fieldnames
        )

    for row_idx, row in enumerate(reader, start=2):
        # Skip SAP footer lines (they often start with '*' or are empty)
        raw_values = list(row.values())
        if not any(v and v.strip() for v in raw_values):
            continue
        first_val = raw_values[0].strip() if raw_values else ''
        if first_val.startswith('*') or first_val.lower() in ('total', 'gesamt', 'summe'):
            continue

        canonical_row = to_canonical_row(row, header_map)
        logger.debug("SAP parser: row %d canonical=%r", row_idx, canonical_row)

        raw_data = dict(row)
        result = SapParseResult(row_number=row_idx, raw_data=raw_data)

        # Movement type filter — skip non-consumption movements silently
        movement = canonical_row.get('movement', '').strip()
        if movement and movement not in _CONSUMPTION_MOVEMENTS:
            continue

        # Required fields
        if 'plant' not in canonical_row or not canonical_row['plant']:
            result.errors.append("Missing plant (WERKS)")

        quantity_str = canonical_row.get('quantity', '').replace(',', '.').strip()
        if not quantity_str:
            result.errors.append("Missing quantity (MENGE)")
        else:
            try:
                result.quantity_raw = Decimal(quantity_str)
            except InvalidOperation:
                result.errors.append(f"Non-numeric quantity: '{quantity_str}'")

        unit_raw = canonical_row.get('unit', '').strip().upper()
        if not unit_raw:
            result.warnings.append("Missing unit (MEINS) — unit conversion skipped; manual review required")

        date_str = canonical_row.get('post_date', '').strip()
        if not date_str:
            result.errors.append("Missing posting date (BUDAT)")
        else:
            try:
                result.post_date = _parse_sap_date(date_str)
            except ValueError as e:
                result.errors.append(str(e))

        if result.errors:
            yield result
            continue

        result.plant = canonical_row.get('plant', '')
        result.material = canonical_row.get('material', '')
        result.description = canonical_row.get('description', '')
        result.cost_center = canonical_row.get('cost_center', '')
        result.unit_raw = unit_raw
        result.fuel_type = _detect_fuel_type(result.description)

        # Analyst-review flags (row is ingested; analyst must sign off)
        if not result.fuel_type:
            result.flags.append(
                f"Could not identify fuel type from description '{result.description}' — "
                "emission factor will not be applied; manual review required"
            )

        if result.quantity_raw < 0:
            result.flags.append(
                f"Negative quantity ({result.quantity_raw}) — possible return/reversal; verify before approving"
            )
        elif result.quantity_raw == 0:
            result.warnings.append(f"Zero quantity ({result.quantity_raw}) — suspicious")

        # Normalize units
        if not unit_raw:
            result.quantity_normalized = result.quantity_raw
            result.unit_normalized = ''
        else:
            result.quantity_normalized, result.unit_normalized = _normalize_quantity(
                result.quantity_raw, result.unit_raw, result.fuel_type
            )

        if unit_raw and result.unit_normalized == result.unit_raw and result.unit_raw not in ('L', 'M3', 'KWH', 'KG'):
            result.warnings.append(
                f"Unit '{result.unit_raw}' not in known SAP UoM table — "
                "no conversion applied; verify manually"
            )

        yield result
