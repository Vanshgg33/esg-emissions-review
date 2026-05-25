from decimal import Decimal
from datetime import date
from django.db import transaction
from django.db.models import Sum, Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.response import Response

from apps.core.models import Tenant
from .models import (
    DataIngestion, RawRecord, NormalizedRecord,
    EmissionFactor, AuditEvent
)
from .serializers import (
    TenantSerializer, DataIngestionSerializer,
    NormalizedRecordSerializer, AuditEventSerializer
)
from .parsers import sap as sap_parser
from .parsers import utility as utility_parser
from .parsers import travel as travel_parser


# ---------------------------------------------------------------------------
# Emission factors (kg CO2e per normalized unit)
# DEFRA UK GHG Conversion Factors 2023 v1.0 for fuels/electricity
# ICAO methodology for aviation (includes RFI multiplier of 1.9)
# GHG Protocol Scope 3 Standard for hotels
# ---------------------------------------------------------------------------

_EF: dict[str, dict] = {
    # Liquid fuels — per litre
    'diesel':       {'value': Decimal('2.68783'), 'unit': 'kg CO2e/L',     'source': 'DEFRA 2023'},
    'heating_oil':  {'value': Decimal('2.54038'), 'unit': 'kg CO2e/L',     'source': 'DEFRA 2023'},
    'petrol':       {'value': Decimal('2.31367'), 'unit': 'kg CO2e/L',     'source': 'DEFRA 2023'},
    'lpg':          {'value': Decimal('1.50936'), 'unit': 'kg CO2e/L',     'source': 'DEFRA 2023'},
    # Gaseous fuels — per m³
    'natural_gas':  {'value': Decimal('2.04000'), 'unit': 'kg CO2e/M3',    'source': 'DEFRA 2023'},
    # Electricity — per kWh (UK market-based)
    'electricity':  {'value': Decimal('0.20700'), 'unit': 'kg CO2e/kWh',   'source': 'DEFRA 2023'},
    # Aviation — per km per passenger (economy, includes RFI factor 1.9)
    'air_economy_short':  {'value': Decimal('0.25500'), 'unit': 'kg CO2e/km', 'source': 'ICAO 2023'},
    'air_economy_long':   {'value': Decimal('0.19500'), 'unit': 'kg CO2e/km', 'source': 'ICAO 2023'},
    'air_business_short': {'value': Decimal('0.38250'), 'unit': 'kg CO2e/km', 'source': 'ICAO 2023'},
    'air_business_long':  {'value': Decimal('0.39000'), 'unit': 'kg CO2e/km', 'source': 'ICAO 2023'},
    'air_first_long':     {'value': Decimal('0.58500'), 'unit': 'kg CO2e/km', 'source': 'ICAO 2023'},
    # Ground transport — per km
    'car_rental':   {'value': Decimal('0.17100'), 'unit': 'kg CO2e/km',    'source': 'DEFRA 2023'},
    'taxi':         {'value': Decimal('0.14900'), 'unit': 'kg CO2e/km',    'source': 'DEFRA 2023'},
    'rail':         {'value': Decimal('0.04100'), 'unit': 'kg CO2e/km',    'source': 'DEFRA 2023'},
    # Hotel — per room-night
    'hotel':        {'value': Decimal('31.40000'), 'unit': 'kg CO2e/night', 'source': 'GHG Protocol Scope 3 2022'},
}


def _get_air_ef_key(class_of_travel: str, distance_km: Decimal) -> str:
    is_long = distance_km > Decimal('3700')
    haul = 'long' if is_long else 'short'
    cls = class_of_travel or 'economy'
    key = f'air_{cls}_{haul}'
    return key if key in _EF else f'air_economy_{haul}'


def _build_flags(record_data: dict) -> tuple[list[str], bool]:
    flags = []
    suspicious = False

    qty = record_data.get('activity_quantity', Decimal('0'))
    if qty <= 0:
        flags.append("Zero or negative activity quantity")
        suspicious = True

    period_start = record_data.get('period_start')
    period_end = record_data.get('period_end')
    if period_start and period_end:
        today = date.today()
        if period_end > today:
            flags.append(f"Period end {period_end} is in the future")
            suspicious = True
        days = (period_end - period_start).days
        if days < 0:
            flags.append("Period end is before period start")
            suspicious = True

    co2e = record_data.get('co2e_kg', Decimal('0'))
    if co2e > Decimal('100000'):
        flags.append(f"Very high CO2e ({co2e:.0f} kg) — verify quantity and unit")
        suspicious = True

    return flags, suspicious


# ---------------------------------------------------------------------------
# Tenant endpoints
# ---------------------------------------------------------------------------

@api_view(['GET', 'POST'])
def tenant_list(request):
    if request.method == 'GET':
        tenants = Tenant.objects.all().order_by('name')
        return Response(TenantSerializer(tenants, many=True).data)

    serializer = TenantSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    tenant = serializer.save()
    return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Ingestion upload
# ---------------------------------------------------------------------------

@api_view(['POST'])
@parser_classes([MultiPartParser, FormParser])
def upload_file(request):
    """
    Upload a source file and trigger synchronous parsing + normalisation.
    Returns the created DataIngestion with a summary of rows processed.
    """
    tenant_id = request.data.get('tenant_id')
    source_type = request.data.get('source_type')
    uploaded_file = request.FILES.get('file')
    ingested_by = request.data.get('ingested_by', 'analyst')

    if not all([tenant_id, source_type, uploaded_file]):
        return Response(
            {'error': 'tenant_id, source_type, and file are required'},
            status=status.HTTP_400_BAD_REQUEST
        )

    valid_types = [c[0] for c in DataIngestion.SourceType.choices]
    if source_type not in valid_types:
        return Response(
            {'error': f'source_type must be one of: {valid_types}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        return Response({'error': 'Tenant not found'}, status=status.HTTP_404_NOT_FOUND)

    # Read content before Django's FileField consumes the file pointer on save
    file_content = uploaded_file.read()

    ingestion = DataIngestion.objects.create(
        tenant=tenant,
        source_type=source_type,
        status=DataIngestion.Status.PROCESSING,
        ingested_by=ingested_by,
        raw_file=uploaded_file,
        original_filename=uploaded_file.name,
    )

    AuditEvent.objects.create(
        tenant=tenant,
        ingestion=ingestion,
        event_type=AuditEvent.EventType.INGESTION_STARTED,
        actor=ingested_by,
        after_state={'source_type': source_type, 'filename': uploaded_file.name},
    )
    log = []

    try:
        with transaction.atomic():
            if source_type == DataIngestion.SourceType.SAP_FUEL:
                _process_sap(ingestion, tenant, file_content, log, ingested_by)
            elif source_type == DataIngestion.SourceType.UTILITY_ELECTRICITY:
                _process_utility(ingestion, tenant, file_content, log, ingested_by)
            elif source_type == DataIngestion.SourceType.TRAVEL:
                _process_travel(ingestion, tenant, file_content, log, ingested_by)

        ingestion.status = DataIngestion.Status.COMPLETE
    except Exception as exc:
        ingestion.status = DataIngestion.Status.FAILED
        log.append({'level': 'error', 'row': None, 'message': str(exc)})
        AuditEvent.objects.create(
            tenant=tenant,
            ingestion=ingestion,
            event_type=AuditEvent.EventType.INGESTION_FAILED,
            actor=ingested_by,
            note=str(exc),
        )

    ingestion.processing_log = log
    ingestion.save()

    if ingestion.status == DataIngestion.Status.COMPLETE:
        AuditEvent.objects.create(
            tenant=tenant,
            ingestion=ingestion,
            event_type=AuditEvent.EventType.INGESTION_COMPLETE,
            actor=ingested_by,
            after_state={
                'row_count': ingestion.row_count,
                'error_count': ingestion.error_count,
                'warning_count': ingestion.warning_count,
            },
        )

    return Response(DataIngestionSerializer(ingestion).data, status=status.HTTP_201_CREATED)


def _process_sap(ingestion, tenant, content, log, actor):
    row_count = error_count = warning_count = 0

    for result in sap_parser.parse(content):
        row_count += 1
        raw = RawRecord.objects.create(
            ingestion=ingestion,
            row_number=result.row_number,
            raw_data=result.raw_data,
            parse_status=(
                RawRecord.ParseStatus.ERROR if result.errors
                else RawRecord.ParseStatus.WARNING if result.warnings
                else RawRecord.ParseStatus.OK
            ),
            parse_errors=result.errors,
        )

        if result.errors:
            error_count += 1
            for err in result.errors:
                log.append({'level': 'error', 'row': result.row_number, 'message': err})
            continue

        if result.warnings:
            warning_count += 1
            for w in result.warnings:
                log.append({'level': 'warning', 'row': result.row_number, 'message': w})

        # Only create normalized record if we can identify a fuel type
        if not result.fuel_type:
            # Treat as purchased goods (Scope 3) with no emission factor
            scope = NormalizedRecord.Scope.SCOPE_3
            category = NormalizedRecord.Category.PURCHASED_GOODS
            ef_key = None
        else:
            scope = NormalizedRecord.Scope.SCOPE_1
            category = NormalizedRecord.Category.STATIONARY_COMBUSTION
            ef_key = result.fuel_type

        ef = _EF.get(ef_key, {'value': Decimal('0'), 'unit': 'N/A', 'source': 'N/A'}) if ef_key else {'value': Decimal('0'), 'unit': 'N/A', 'source': 'Manual lookup required'}

        co2e = result.quantity_normalized * ef['value']

        record_data = {
            'activity_quantity': result.quantity_normalized,
            'period_start': result.post_date,
            'period_end': result.post_date,
            'co2e_kg': co2e,
        }
        flags, suspicious = _build_flags(record_data)
        flags.extend(result.warnings)

        plant_name = sap_parser.PLANT_NAMES.get(result.plant, result.plant)

        nr = NormalizedRecord.objects.create(
            tenant=tenant,
            source_record=raw,
            scope=scope,
            category=category,
            facility_id=result.plant,
            facility_name=plant_name,
            description=result.description,
            period_start=result.post_date,
            period_end=result.post_date,
            activity_quantity_raw=result.quantity_raw,
            activity_unit_raw=result.unit_raw,
            activity_quantity=result.quantity_normalized,
            activity_unit=result.unit_normalized,
            emission_factor_value=ef['value'],
            emission_factor_unit=ef['unit'],
            emission_factor_source=ef['source'],
            co2e_kg=co2e,
            flags=flags,
            is_suspicious=suspicious,
        )
        AuditEvent.objects.create(
            tenant=tenant, record=nr, ingestion=ingestion,
            event_type=AuditEvent.EventType.RECORD_CREATED, actor=actor,
            after_state={'co2e_kg': str(co2e), 'scope': scope},
        )

    ingestion.row_count = row_count
    ingestion.error_count = error_count
    ingestion.warning_count = warning_count
    ingestion.save(update_fields=['row_count', 'error_count', 'warning_count'])


def _process_utility(ingestion, tenant, content, log, actor):
    row_count = error_count = warning_count = 0

    for result in utility_parser.parse(content):
        row_count += 1
        raw = RawRecord.objects.create(
            ingestion=ingestion,
            row_number=result.row_number,
            raw_data=result.raw_data,
            parse_status=(
                RawRecord.ParseStatus.ERROR if result.errors
                else RawRecord.ParseStatus.WARNING if result.warnings
                else RawRecord.ParseStatus.OK
            ),
            parse_errors=result.errors,
        )

        if result.errors:
            error_count += 1
            for err in result.errors:
                log.append({'level': 'error', 'row': result.row_number, 'message': err})
            continue

        if result.warnings:
            warning_count += 1
            for w in result.warnings:
                log.append({'level': 'warning', 'row': result.row_number, 'message': w})

        ef = _EF['electricity']
        co2e = result.kwh_normalized * ef['value']

        record_data = {
            'activity_quantity': result.kwh_normalized,
            'period_start': result.period_start,
            'period_end': result.period_end,
            'co2e_kg': co2e,
        }
        flags, suspicious = _build_flags(record_data)
        flags.extend(result.warnings)

        nr = NormalizedRecord.objects.create(
            tenant=tenant,
            source_record=raw,
            scope=NormalizedRecord.Scope.SCOPE_2,
            category=NormalizedRecord.Category.PURCHASED_ELECTRICITY,
            facility_id=result.meter_id or result.account_number,
            facility_name=result.service_address,
            description=f"Account {result.account_number}" + (f" | Tariff {result.tariff_code}" if result.tariff_code else ""),
            period_start=result.period_start,
            period_end=result.period_end,
            activity_quantity_raw=result.kwh_raw,
            activity_unit_raw='kWh' if result.kwh_raw == result.kwh_normalized else 'MWh',
            activity_quantity=result.kwh_normalized,
            activity_unit='kWh',
            emission_factor_value=ef['value'],
            emission_factor_unit=ef['unit'],
            emission_factor_source=ef['source'],
            co2e_kg=co2e,
            flags=flags,
            is_suspicious=suspicious,
        )
        AuditEvent.objects.create(
            tenant=tenant, record=nr, ingestion=ingestion,
            event_type=AuditEvent.EventType.RECORD_CREATED, actor=actor,
            after_state={'co2e_kg': str(co2e), 'scope': 2},
        )

    ingestion.row_count = row_count
    ingestion.error_count = error_count
    ingestion.warning_count = warning_count
    ingestion.save(update_fields=['row_count', 'error_count', 'warning_count'])


def _process_travel(ingestion, tenant, content, log, actor):
    row_count = error_count = warning_count = 0

    for result in travel_parser.parse(content):
        row_count += 1
        raw = RawRecord.objects.create(
            ingestion=ingestion,
            row_number=result.row_number,
            raw_data=result.raw_data,
            parse_status=(
                RawRecord.ParseStatus.ERROR if result.errors
                else RawRecord.ParseStatus.WARNING if result.warnings
                else RawRecord.ParseStatus.OK
            ),
            parse_errors=result.errors,
        )

        if result.errors:
            error_count += 1
            for err in result.errors:
                log.append({'level': 'error', 'row': result.row_number, 'message': err})
            continue

        if result.warnings:
            warning_count += 1

        # Map expense category → NormalizedRecord category + EF key
        cat_map = {
            'air':        (NormalizedRecord.Category.BUSINESS_TRAVEL_AIR, None),
            'hotel':      (NormalizedRecord.Category.BUSINESS_TRAVEL_HOTEL, 'hotel'),
            'car_rental': (NormalizedRecord.Category.BUSINESS_TRAVEL_GROUND, 'car_rental'),
            'taxi':       (NormalizedRecord.Category.BUSINESS_TRAVEL_GROUND, 'taxi'),
            'rail':       (NormalizedRecord.Category.BUSINESS_TRAVEL_GROUND, 'rail'),
        }
        category, ef_key = cat_map.get(result.expense_category, (NormalizedRecord.Category.BUSINESS_TRAVEL_GROUND, None))

        if result.expense_category == 'air':
            dist = result.distance_km or Decimal('0')
            ef_key = _get_air_ef_key(result.class_of_travel, dist)

        ef = _EF.get(ef_key, {'value': Decimal('0'), 'unit': 'N/A', 'source': 'N/A'}) if ef_key else {'value': Decimal('0'), 'unit': 'N/A', 'source': 'N/A'}

        # Activity quantity: km for transport, nights for hotel
        if result.expense_category == 'hotel':
            activity_qty = Decimal(str(result.hotel_nights or 1))
            activity_unit = 'nights'
        else:
            activity_qty = result.distance_km or Decimal('0')
            activity_unit = 'km'

        co2e = activity_qty * ef['value']

        record_data = {
            'activity_quantity': activity_qty,
            'period_start': result.transaction_date,
            'period_end': result.transaction_date,
            'co2e_kg': co2e,
        }
        flags, suspicious = _build_flags(record_data)
        flags.extend(result.warnings)
        if activity_qty == 0 and result.expense_category != 'hotel':
            flags.append("Distance is zero — emissions set to 0; manual correction required")
            suspicious = True

        desc_parts = [result.expense_type_raw]
        if result.from_iata and result.to_iata:
            desc_parts.append(f"{result.from_iata}→{result.to_iata}")
        elif result.origin and result.destination:
            desc_parts.append(f"{result.origin}→{result.destination}")
        if result.employee_name:
            desc_parts.append(result.employee_name)

        nr = NormalizedRecord.objects.create(
            tenant=tenant,
            source_record=raw,
            scope=NormalizedRecord.Scope.SCOPE_3,
            category=category,
            facility_id=result.employee_id,
            facility_name=result.vendor,
            description=' | '.join(filter(None, desc_parts)),
            period_start=result.transaction_date,
            period_end=result.transaction_date,
            activity_quantity_raw=activity_qty,
            activity_unit_raw=activity_unit,
            activity_quantity=activity_qty,
            activity_unit=activity_unit,
            emission_factor_value=ef['value'],
            emission_factor_unit=ef['unit'],
            emission_factor_source=ef['source'],
            co2e_kg=co2e,
            flags=flags,
            is_suspicious=suspicious,
        )
        AuditEvent.objects.create(
            tenant=tenant, record=nr, ingestion=ingestion,
            event_type=AuditEvent.EventType.RECORD_CREATED, actor=actor,
            after_state={'co2e_kg': str(co2e), 'scope': 3},
        )

    ingestion.row_count = row_count
    ingestion.error_count = error_count
    ingestion.warning_count = warning_count
    ingestion.save(update_fields=['row_count', 'error_count', 'warning_count'])


# ---------------------------------------------------------------------------
# Ingestion list / detail
# ---------------------------------------------------------------------------

@api_view(['GET'])
def ingestion_list(request):
    tenant_id = request.query_params.get('tenant_id')
    qs = DataIngestion.objects.select_related('tenant')
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    return Response(DataIngestionSerializer(qs[:100], many=True).data)


@api_view(['GET'])
def ingestion_detail(request, pk):
    try:
        ing = DataIngestion.objects.get(pk=pk)
    except DataIngestion.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(DataIngestionSerializer(ing).data)


# ---------------------------------------------------------------------------
# Normalized records — list + review actions
# ---------------------------------------------------------------------------

@api_view(['GET'])
def record_list(request):
    tenant_id = request.query_params.get('tenant_id')
    review_status = request.query_params.get('review_status')
    scope = request.query_params.get('scope')
    source_type = request.query_params.get('source_type')
    suspicious = request.query_params.get('suspicious')
    page = int(request.query_params.get('page', 1))
    page_size = min(int(request.query_params.get('page_size', 50)), 200)

    qs = NormalizedRecord.objects.select_related(
        'tenant', 'source_record', 'source_record__ingestion'
    ).order_by('-period_start')

    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    if review_status:
        qs = qs.filter(review_status=review_status)
    if scope:
        qs = qs.filter(scope=scope)
    if source_type:
        qs = qs.filter(source_record__ingestion__source_type=source_type)
    if suspicious == 'true':
        qs = qs.filter(is_suspicious=True)

    total = qs.count()
    start = (page - 1) * page_size
    records = qs[start:start + page_size]

    return Response({
        'count': total,
        'page': page,
        'page_size': page_size,
        'results': NormalizedRecordSerializer(records, many=True).data,
    })


@api_view(['GET'])
def record_detail(request, pk):
    try:
        record = NormalizedRecord.objects.select_related(
            'source_record', 'source_record__ingestion', 'tenant'
        ).get(pk=pk)
    except NormalizedRecord.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(NormalizedRecordSerializer(record).data)


@api_view(['PATCH'])
def record_review(request, pk):
    """Update review status for a single record."""
    try:
        record = NormalizedRecord.objects.get(pk=pk)
    except NormalizedRecord.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if record.is_locked:
        return Response(
            {'error': 'Record is locked for audit and cannot be modified'},
            status=status.HTTP_409_CONFLICT
        )

    new_status = request.data.get('review_status')
    notes = request.data.get('review_notes', record.review_notes)
    actor = request.data.get('actor', 'analyst')
    lock = request.data.get('lock', False)

    valid_statuses = [c[0] for c in NormalizedRecord.ReviewStatus.choices]
    if new_status and new_status not in valid_statuses:
        return Response({'error': f'Invalid review_status. Must be one of: {valid_statuses}'}, status=400)

    before = {
        'review_status': record.review_status,
        'review_notes': record.review_notes,
        'is_locked': record.is_locked,
    }

    if new_status:
        record.review_status = new_status
    record.review_notes = notes
    record.reviewed_by = actor
    record.reviewed_at = timezone.now()

    if lock and new_status == NormalizedRecord.ReviewStatus.APPROVED:
        record.is_locked = True
        record.locked_at = timezone.now()
        record.locked_by = actor

    record.save()

    after = {
        'review_status': record.review_status,
        'review_notes': record.review_notes,
        'is_locked': record.is_locked,
    }

    event_type = (
        AuditEvent.EventType.RECORD_LOCKED if record.is_locked
        else AuditEvent.EventType.RECORD_FLAGGED if new_status == 'FLAGGED'
        else AuditEvent.EventType.RECORD_REVIEWED
    )
    AuditEvent.objects.create(
        tenant=record.tenant, record=record,
        event_type=event_type, actor=actor,
        before_state=before, after_state=after,
        note=notes,
    )

    return Response(NormalizedRecordSerializer(record).data)


@api_view(['POST'])
def bulk_review(request):
    """Approve or reject multiple records in one call."""
    record_ids = request.data.get('record_ids', [])
    new_status = request.data.get('review_status')
    actor = request.data.get('actor', 'analyst')
    notes = request.data.get('review_notes', '')

    if not record_ids or not new_status:
        return Response({'error': 'record_ids and review_status are required'}, status=400)

    valid_statuses = [c[0] for c in NormalizedRecord.ReviewStatus.choices]
    if new_status not in valid_statuses:
        return Response({'error': f'Invalid review_status'}, status=400)

    records = NormalizedRecord.objects.filter(pk__in=record_ids, is_locked=False)
    updated = 0
    for record in records:
        before = {'review_status': record.review_status}
        record.review_status = new_status
        record.reviewed_by = actor
        record.reviewed_at = timezone.now()
        if notes:
            record.review_notes = notes
        record.save()
        AuditEvent.objects.create(
            tenant=record.tenant, record=record,
            event_type=AuditEvent.EventType.BULK_REVIEW, actor=actor,
            before_state=before,
            after_state={'review_status': new_status},
            note=notes,
        )
        updated += 1

    return Response({'updated': updated, 'skipped_locked': len(record_ids) - updated})


@api_view(['GET'])
def record_audit(request, pk):
    """Audit trail for a specific record."""
    events = AuditEvent.objects.filter(record_id=pk).order_by('-timestamp')
    return Response(AuditEventSerializer(events, many=True).data)


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

@api_view(['GET'])
def dashboard_stats(request):
    tenant_id = request.query_params.get('tenant_id')
    qs = NormalizedRecord.objects.all()
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)

    total = qs.count()
    pending = qs.filter(review_status='PENDING').count()
    approved = qs.filter(review_status='APPROVED').count()
    flagged = qs.filter(review_status='FLAGGED').count()
    suspicious = qs.filter(is_suspicious=True).count()

    scope_totals = {}
    for scope_val in [1, 2, 3]:
        agg = qs.filter(scope=scope_val).aggregate(total=Sum('co2e_kg'), count=Count('id'))
        scope_totals[f'scope_{scope_val}'] = {
            'co2e_kg': float(agg['total'] or 0),
            'count': agg['count'],
        }

    total_co2e = qs.aggregate(total=Sum('co2e_kg'))['total'] or 0

    recent_ingestions = DataIngestion.objects.all()
    if tenant_id:
        recent_ingestions = recent_ingestions.filter(tenant_id=tenant_id)
    recent_ingestions = recent_ingestions[:5]

    return Response({
        'total_records': total,
        'pending_review': pending,
        'approved': approved,
        'flagged': flagged,
        'suspicious': suspicious,
        'total_co2e_kg': float(total_co2e),
        'total_co2e_tonnes': float(total_co2e) / 1000,
        'by_scope': scope_totals,
        'recent_ingestions': DataIngestionSerializer(recent_ingestions, many=True).data,
    })
