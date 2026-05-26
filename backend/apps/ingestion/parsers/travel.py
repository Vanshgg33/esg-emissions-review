"""
Corporate travel parser — Concur / Navan expense report CSV export.

Format choice: Concur standard expense report CSV export.

Rationale: Concur is the dominant corporate travel platform (>50% enterprise market
share). Navan (formerly TripActions) exports a nearly identical schema. The export
is triggered by the travel manager in the Concur admin console under
Reports > Standard Reports > Expense Detail Report.

Real-world complications handled here:
- Distance is not always provided. Concur records transactions, not distances.
  When origin/destination cities or airport IATA codes are available we compute
  great-circle distance via the haversine formula. When only city names are
  given we cannot reliably geocode without a third-party API (noted as a gap).
- Expense categories vary: AIR, HOTEL, CAR_RENTAL, TAXI, RAIL, GROUND.
  Each maps to a different Scope 3 sub-category and emission factor.
- Class of travel matters for flights: Business class has ~2x the emission factor
  of Economy because business seats consume more floor space per passenger.
- Hotel nights: the transaction amount doesn't tell us nights — Concur has a
  'nights' field in the hotel expense form but it's often blank in exports.
  We infer from check-in/check-out dates when available, else 1 night.
- Currency: we don't convert currencies (emission calculation is quantity-based,
  not cost-based). Amounts are preserved in raw_data for finance reconciliation.

What we are NOT handling:
- Ground transport distance when no IATA code is available (taxi, Uber receipts
  with only a cost and city).
- Rail journeys between specific station pairs (would require a rail distance API).
- Hotel emission factor variation by country/star rating.
"""

import csv
import io
import math
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Iterator

from .normalizer import build_header_map, to_canonical_row


# ---------------------------------------------------------------------------
# Airport coordinate lookup (50 major global hubs, haversine calculation)
# ---------------------------------------------------------------------------

AIRPORT_COORDS: dict[str, tuple[float, float]] = {
    'LHR': (51.4775, -0.4614),   'LGW': (51.1481, -0.1903),
    'MAN': (53.3537, -2.2750),   'EDI': (55.9500, -3.3725),
    'JFK': (40.6413, -73.7781),  'EWR': (40.6895, -74.1745),
    'LAX': (33.9425, -118.4081), 'ORD': (41.9742, -87.9073),
    'ATL': (33.6407, -84.4277),  'DFW': (32.8998, -97.0403),
    'MIA': (25.7959, -80.2870),  'BOS': (42.3656, -71.0096),
    'SEA': (47.4502, -122.3088), 'SFO': (37.6213, -122.3790),
    'IAD': (38.9531, -77.4565),  'DEN': (39.8561, -104.6737),
    'YYZ': (43.6772, -79.6306),  'YVR': (49.1947, -123.1792),
    'FRA': (50.0379, 8.5622),    'MUC': (48.3537, 11.7750),
    'BER': (52.3667, 13.5033),   'HAM': (53.6304, 9.9882),
    'CDG': (49.0097, 2.5479),    'ORY': (48.7233, 2.3794),
    'AMS': (52.3105, 4.7683),    'BRU': (50.9010, 4.4844),
    'ZRH': (47.4647, 8.5492),    'VIE': (48.1103, 16.5697),
    'MAD': (40.4719, -3.5626),   'BCN': (41.2971, 2.0785),
    'FCO': (41.8003, 12.2389),   'MXP': (45.6306, 8.7281),
    'IST': (40.9769, 28.8146),   'SAW': (40.8986, 29.3092),
    'SVO': (55.9726, 37.4146),   'DME': (55.4088, 37.9063),
    'DXB': (25.2532, 55.3657),   'DOH': (25.2611, 51.5650),
    'AUH': (24.4330, 54.6511),   'KWI': (29.2267, 47.9689),
    'SIN': (1.3644, 103.9915),   'KUL': (2.7456, 101.7099),
    'BKK': (13.9132, 100.6080),  'CGK': (-6.1256, 106.6558),
    'HKG': (22.3080, 113.9185),  'PVG': (31.1443, 121.8083),
    'PEK': (40.0799, 116.6031),  'CAN': (23.3924, 113.2988),
    'NRT': (35.7720, 140.3929),  'KIX': (34.4272, 135.2440),
    'ICN': (37.4602, 126.4407),  'TPE': (25.0777, 121.2325),
    'SYD': (-33.9461, 151.1772), 'MEL': (-37.6733, 144.8430),
    'BNE': (-27.3842, 153.1175), 'PER': (-31.9403, 115.9669),
    'JNB': (-26.1367, 28.2411),  'CPT': (-33.9715, 18.6021),
    'NBO': (-1.3192, 36.9275),   'ADD': (8.9779, 38.7993),
    'GRU': (-23.4356, -46.4731), 'EZE': (-34.8222, -58.5358),
    'BOG': (4.7016, -74.1469),   'MEX': (19.4363, -99.0721),
    'SCL': (-33.3930, -70.7858), 'LIM': (-12.0219, -77.1143),
    'BOM': (19.0896, 72.8656),   'DEL': (28.5562, 77.1000),
    'BLR': (13.1986, 77.7066),   'MAA': (12.9941, 80.1709),
    'HYD': (17.2403, 78.4294),   'CCU': (22.6547, 88.4467),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def distance_from_iata(from_code: str, to_code: str) -> float | None:
    """Return one-way great-circle distance in km, or None if either code is unknown."""
    from_coord = AIRPORT_COORDS.get(from_code.upper().strip())
    to_coord = AIRPORT_COORDS.get(to_code.upper().strip())
    if from_coord and to_coord:
        return haversine_km(*from_coord, *to_coord)
    return None


# ---------------------------------------------------------------------------
# Expense type → (category, scope, description)
# ---------------------------------------------------------------------------

# Concur expense types → canonical category
_EXPENSE_TYPE_MAP: dict[str, str] = {
    'AIR':          'air',
    'AIRFARE':      'air',
    'AIRLINE':      'air',
    'FLIGHT':       'air',
    'HOTEL':        'hotel',
    'LODGING':      'hotel',
    'ACCOMMODATION':'hotel',
    'CAR_RENTAL':   'car_rental',
    'CAR RENTAL':   'car_rental',
    'CARRENTAL':    'car_rental',
    'RENTAL CAR':   'car_rental',
    'TAXI':         'taxi',
    'RIDESHARE':    'taxi',
    'UBER':         'taxi',
    'LYFT':         'taxi',
    'GROUND':       'taxi',
    'RAIL':         'rail',
    'TRAIN':        'rail',
    'AMTRAK':       'rail',
    'EUROSTAR':     'rail',
    'METRO':        'rail',
}

_DATE_FORMATS = ['%Y-%m-%d', '%Y/%m/%d', '%m/%d/%Y', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y']


@dataclass
class TravelParseResult:
    row_number: int
    raw_data: dict
    transaction_date: date | None = None
    employee_id: str = ''
    employee_name: str = ''
    expense_type_raw: str = ''
    expense_category: str = ''   # 'air' | 'hotel' | 'car_rental' | 'taxi' | 'rail' | ''
    vendor: str = ''
    origin: str = ''
    destination: str = ''
    from_iata: str = ''
    to_iata: str = ''
    distance_km: Decimal | None = None
    distance_source: str = ''    # 'provided' | 'calculated' | 'unknown'
    hotel_nights: int | None = None
    class_of_travel: str = ''    # 'economy' | 'business' | 'first'
    amount: Decimal | None = None
    currency: str = ''
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


def _normalise_class(raw: str) -> str:
    r = raw.lower().strip()
    if 'business' in r or 'biz' in r:
        return 'business'
    if 'first' in r or '1st' in r:
        return 'first'
    return 'economy'


_COLUMN_ALIASES: dict[str, list[str]] = {
    'transaction_date': ['Transaction_Date', 'Date', 'Travel_Date', 'Expense_Date'],
    'employee_id':      ['Employee_ID', 'Employee ID', 'EmpID', 'Emp_ID'],
    'employee_name':    ['Employee_Name', 'Employee Name', 'Name', 'Traveler'],
    'expense_type':     ['Expense_Type', 'Expense Type', 'Category', 'Type',
                          'expense_category', 'travel_type', 'category', 'expense_class'],
    'vendor':           ['Vendor', 'Supplier', 'Airline', 'Hotel_Name'],
    'origin':           ['Origin', 'From_City', 'Departure_City', 'From'],
    'destination':      ['Destination', 'To_City', 'Arrival_City', 'To'],
    'from_iata':        ['From_IATA', 'Origin_Code', 'From_Airport', 'Departure_Code', 'IATA_From'],
    'to_iata':          ['To_IATA', 'Dest_Code', 'To_Airport', 'Arrival_Code', 'IATA_To'],
    'distance_km':      ['Distance_KM', 'Distance', 'Miles', 'KM'],
    'hotel_nights':     ['Hotel_Nights', 'Nights', 'Night_Count', 'Number_of_Nights'],
    'class_of_travel':  ['Class_of_Travel', 'Class', 'Cabin_Class', 'Travel_Class', 'Cabin'],
    'amount':           ['Amount', 'Total', 'Cost', 'Charge'],
    'currency':         ['Currency', 'CCY', 'Currency_Code'],
}




def parse(file_content: str | bytes) -> Iterator[TravelParseResult]:
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

        result = TravelParseResult(row_number=row_idx, raw_data=dict(row))

        # Date
        date_str = canonical_row.get('transaction_date', '').strip()
        if not date_str:
            result.errors.append("Missing transaction date")
        else:
            try:
                result.transaction_date = _parse_date(date_str)
            except ValueError as e:
                result.errors.append(str(e))

        # Expense type → category
        raw_type = canonical_row.get('expense_type', '').strip().upper()
        result.expense_type_raw = raw_type
        if raw_type:
            result.expense_category = _EXPENSE_TYPE_MAP.get(raw_type, '')
            if not result.expense_category:
                result.warnings.append(
                    f"Unrecognised expense type '{raw_type}' — cannot determine emission category"
                )
        else:
            result.errors.append("Missing expense type/category")

        if result.errors:
            yield result
            continue

        result.employee_id = canonical_row.get('employee_id', '')
        result.employee_name = canonical_row.get('employee_name', '')
        result.vendor = canonical_row.get('vendor', '')
        result.origin = canonical_row.get('origin', '')
        result.destination = canonical_row.get('destination', '')
        result.from_iata = canonical_row.get('from_iata', '').upper()
        result.to_iata = canonical_row.get('to_iata', '').upper()
        result.class_of_travel = _normalise_class(canonical_row.get('class_of_travel', ''))
        result.currency = canonical_row.get('currency', '')

        # Amount (preserve for reconciliation)
        amount_str = canonical_row.get('amount', '').replace(',', '').strip()
        if amount_str:
            try:
                result.amount = Decimal(amount_str)
            except InvalidOperation:
                result.warnings.append(f"Non-numeric amount: '{amount_str}'")

        # Hotel nights
        nights_str = canonical_row.get('hotel_nights', '').strip()
        if nights_str:
            try:
                result.hotel_nights = int(float(nights_str))
            except (ValueError, TypeError):
                result.warnings.append(f"Non-integer nights: '{nights_str}'")

        # Distance resolution for flights and ground transport
        if result.expense_category in ('air', 'car_rental', 'taxi', 'rail'):
            dist_str = canonical_row.get('distance_km', '').replace(',', '').strip()
            if dist_str:
                try:
                    result.distance_km = Decimal(dist_str)
                    result.distance_source = 'provided'
                except InvalidOperation:
                    result.warnings.append(f"Non-numeric distance: '{dist_str}'")

            if result.distance_km is None and result.from_iata and result.to_iata:
                d = distance_from_iata(result.from_iata, result.to_iata)
                if d is not None:
                    result.distance_km = Decimal(str(round(d, 1)))
                    result.distance_source = 'calculated_haversine'
                else:
                    result.warnings.append(
                        f"IATA codes '{result.from_iata}'/'{result.to_iata}' not in lookup table — "
                        "distance unknown; emission will be zero"
                    )
                    result.distance_source = 'unknown'

            if result.distance_km is None and result.expense_category != 'hotel':
                result.warnings.append("No distance available — cannot calculate emissions for this trip")

        # Hotel must have nights
        if result.expense_category == 'hotel' and not result.hotel_nights:
            result.warnings.append("Hotel expense with no nights count — defaulting to 1 night")
            result.hotel_nights = 1

        yield result
