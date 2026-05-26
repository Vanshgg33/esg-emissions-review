"""
Utility electricity parser — portal CSV export format.

Format choice: Portal CSV export (not PDF bill, not Green Button XML API).

Rationale: The majority of UK/EU/US facilities teams download a CSV from their
utility portal monthly. Green Button XML is theoretically available for US
residential and some commercial accounts but is rarely enabled by default for
enterprise accounts with complex tariff structures. PDFs require OCR and are
error-prone. The portal CSV is the realistic middle ground: structured enough
to parse reliably, messy enough to need careful handling.

Real-world complications handled here:
- Billing periods that don't align with calendar months (a meter read happens
  when the utility technician visits, not on the 1st). A billing period of
  2024-01-03 to 2024-02-05 is entirely normal.
- kWh vs MWh: industrial accounts often export in MWh. We normalise to kWh.
- Demand charges (peak_kw) are in the export but not used for emissions;
  they're preserved in raw_data for completeness.
- Multiple meters per account at the same address. Each meter row produces an
  independent NormalizedRecord.
- Estimated vs actual reads: some exports mark rows as 'E' (estimated) or 'A'
  (actual). Estimated readings get a quality flag.

What we are NOT handling:
- Time-of-use (TOU) tariff breakdowns (on-peak vs off-peak kWh) — we sum total
  consumption per billing period.
- Half-hourly interval data (HH data) — facilities with smart meters export this
  but it's a different format entirely (48 rows per day per meter).
- Reactive power / power factor charges.
"""

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator

from .normalizer import build_header_map, to_canonical_row


_DATE_FORMATS = ['%Y-%m-%d', '%Y/%m/%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y', '%d.%m.%Y']


@dataclass
class UtilityParseResult:
    row_number: int
    raw_data: dict
    account_number: str = ''
    meter_id: str = ''
    service_address: str = ''
    period_start: date | None = None
    period_end: date | None = None
    kwh_raw: Decimal = Decimal('0')
    kwh_normalized: Decimal = Decimal('0')
    tariff_code: str = ''
    read_type: str = ''   # 'actual' | 'estimated' | ''
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _parse_date(raw: str) -> date:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date format: '{raw}'")


# Flexible column header matching
_COLUMN_ALIASES: dict[str, list[str]] = {
    'account_number': ['Account_Number', 'Account Number', 'AccountNumber', 'account_no', 'ACC'],
    'meter_id':       ['Meter_ID', 'Meter ID', 'MeterID', 'Meter', 'meter_id', 'MPAN', 'MPRN'],
    'service_address':['Service_Address', 'Service Address', 'Address', 'Site'],
    'period_start':   ['Read_Start', 'From', 'Start_Date', 'Bill_Start', 'Period_Start', 'StartDate',
                        'billing_start', 'start_date', 'from_date'],
    'period_end':     ['Read_End', 'To', 'End_Date', 'Bill_End', 'Period_End', 'EndDate',
                        'billing_end', 'end_date', 'to_date'],
    'kwh_usage':      ['kWh_Usage', 'kWh', 'Usage_kWh', 'Energy_kWh', 'kwh', 'Consumption'],
    'mwh_usage':      ['MWh_Usage', 'MWh', 'Usage_MWh', 'Energy_MWh', 'mwh'],
    'tariff_code':    ['Tariff_Code', 'Tariff', 'Rate_Code', 'Rate', 'tariff'],
    'read_type':      ['Read_Type', 'Read Type', 'Type', 'Estimated'],
}




def parse(file_content: str | bytes) -> Iterator[UtilityParseResult]:
    """
    Parse a utility portal CSV export. Yields one UtilityParseResult per row.
    """
    if isinstance(file_content, bytes):
        for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
            try:
                file_content = file_content.decode(enc)
                break
            except UnicodeDecodeError:
                continue

    reader = csv.DictReader(io.StringIO(file_content))
    if not reader.fieldnames:
        return

    header_map = build_header_map(reader.fieldnames, _COLUMN_ALIASES)

    for row_idx, row in enumerate(reader, start=2):
        raw_values = list(row.values())
        if not any(v and v.strip() for v in raw_values):
            continue

        canonical_row = to_canonical_row(row, header_map)

        result = UtilityParseResult(row_number=row_idx, raw_data=dict(row))

        # Dates
        for field_name, label in (('period_start', 'Read_Start'), ('period_end', 'Read_End')):
            raw_date = canonical_row.get(field_name, '')
            if not raw_date:
                result.errors.append(f"Missing {label}")
            else:
                try:
                    setattr(result, field_name, _parse_date(raw_date))
                except ValueError as e:
                    result.errors.append(str(e))

        # Energy quantity — prefer kWh, fall back to MWh
        kwh_str = canonical_row.get('kwh_usage', '').replace(',', '').strip()
        mwh_str = canonical_row.get('mwh_usage', '').replace(',', '').strip()

        if kwh_str:
            try:
                result.kwh_raw = Decimal(kwh_str)
                result.kwh_normalized = result.kwh_raw
            except InvalidOperation:
                result.errors.append(f"Non-numeric kWh value: '{kwh_str}'")
        elif mwh_str:
            try:
                mwh = Decimal(mwh_str)
                result.kwh_raw = mwh
                result.kwh_normalized = mwh * Decimal('1000')
            except InvalidOperation:
                result.errors.append(f"Non-numeric MWh value: '{mwh_str}'")
        else:
            result.errors.append("No energy consumption column found (expected kWh or MWh)")

        if result.errors:
            yield result
            continue

        result.account_number = canonical_row.get('account_number', '')
        result.meter_id = canonical_row.get('meter_id', '')
        result.service_address = canonical_row.get('service_address', '')
        result.tariff_code = canonical_row.get('tariff_code', '')
        result.read_type = canonical_row.get('read_type', '').lower()

        # Quality flags
        if result.kwh_normalized <= 0:
            result.warnings.append(f"Zero or negative consumption ({result.kwh_normalized} kWh) — verify")

        if result.period_start and result.period_end:
            days = (result.period_end - result.period_start).days
            if days < 20:
                result.warnings.append(f"Unusually short billing period: {days} days")
            elif days > 40:
                result.warnings.append(f"Unusually long billing period: {days} days — may span two bills")

        if 'estim' in result.read_type or result.read_type == 'e':
            result.warnings.append("Estimated meter read — may be corrected in next period")

        if not result.meter_id:
            result.warnings.append("No meter ID — cannot distinguish multiple meters at same address")

        yield result
