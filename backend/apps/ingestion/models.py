from django.db import models
from apps.core.models import Tenant


class EmissionFactor(models.Model):
    """
    Versioned lookup table for activity-to-CO2e conversion.

    Factors are denormalized into NormalizedRecord at write time so that
    historical records remain stable if we update EF tables. The FK here
    is only for provenance — the actual value used is on the record itself.

    Sources: DEFRA UK GHG Conversion Factors 2023, EPA eGRID 2023,
    ICAO Carbon Emissions Calculator methodology.
    """
    category = models.CharField(max_length=100)       # e.g. 'diesel', 'electricity_uk'
    subcategory = models.CharField(max_length=100, blank=True)  # e.g. 'business_class'
    activity_unit = models.CharField(max_length=20)   # the unit this factor applies to
    kg_co2e_per_unit = models.DecimalField(max_digits=12, decimal_places=6)
    source = models.CharField(max_length=200)          # citation
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)  # null = still current

    class Meta:
        indexes = [models.Index(fields=['category', 'valid_from'])]
        ordering = ['category', '-valid_from']

    def __str__(self):
        return f"{self.category} — {self.kg_co2e_per_unit} kg CO2e/{self.activity_unit} ({self.source})"


class DataIngestion(models.Model):
    """
    One upload/pull event. The raw_file is preserved permanently so we can
    always reproduce what we received, even if parsers change later.
    """
    class SourceType(models.TextChoices):
        SAP_FUEL = 'SAP_FUEL', 'SAP Fuel & Procurement'
        UTILITY_ELECTRICITY = 'UTILITY_ELEC', 'Utility Electricity'
        TRAVEL = 'TRAVEL', 'Corporate Travel'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETE = 'COMPLETE', 'Complete'
        FAILED = 'FAILED', 'Failed'

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='ingestions')
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    ingested_at = models.DateTimeField(auto_now_add=True)
    ingested_by = models.CharField(max_length=200)
    raw_file = models.FileField(upload_to='raw_uploads/%Y/%m/', null=True, blank=True)
    original_filename = models.CharField(max_length=255, blank=True)
    row_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    warning_count = models.IntegerField(default=0)
    # Structured log: [{level, row, message}, ...] so UI can surface parse warnings
    processing_log = models.JSONField(default=list)

    class Meta:
        ordering = ['-ingested_at']

    def __str__(self):
        return f"{self.get_source_type_display()} — {self.ingested_at:%Y-%m-%d %H:%M} ({self.status})"


class RawRecord(models.Model):
    """
    Immutable snapshot of a single row from the source file.

    raw_data holds the original key-value pairs exactly as received, before
    any normalization. This is the authoritative source-of-truth for what
    the client actually sent us. Never update this after creation.
    """
    class ParseStatus(models.TextChoices):
        OK = 'OK', 'Parsed OK'
        WARNING = 'WARNING', 'Parsed with warnings'
        ERROR = 'ERROR', 'Parse error — no normalized record produced'

    ingestion = models.ForeignKey(DataIngestion, on_delete=models.CASCADE, related_name='raw_records')
    row_number = models.IntegerField()
    raw_data = models.JSONField()
    parse_status = models.CharField(max_length=10, choices=ParseStatus.choices, default=ParseStatus.OK)
    parse_errors = models.JSONField(default=list)

    class Meta:
        unique_together = [('ingestion', 'row_number')]
        ordering = ['ingestion', 'row_number']

    def __str__(self):
        return f"Row {self.row_number} of {self.ingestion}"


class NormalizedRecord(models.Model):
    """
    The canonical emissions activity record produced from a RawRecord.

    Design invariants:
    - scope + category together determine the emission calculation method.
    - activity_quantity / activity_unit are in normalized units:
        L for liquid fuels, kWh for electricity, km for distance, nights for hotel.
    - co2e_kg = activity_quantity * emission_factor_value (computed at ingest time,
        not recomputed on reads, so changing the EF table doesn't silently alter history).
    - emission_factor_value / _unit / _source are denormalized snapshots of the EF
        used at ingest time — the EmissionFactor table can change safely.
    - is_locked=True prevents all edits (enforced in API layer, not DB constraint,
        so a superuser can unlock for correction with a full audit trail).
    - Every state change must produce an AuditEvent before returning.
    """
    class Scope(models.IntegerChoices):
        SCOPE_1 = 1, 'Scope 1'
        SCOPE_2 = 2, 'Scope 2'
        SCOPE_3 = 3, 'Scope 3'

    class Category(models.TextChoices):
        STATIONARY_COMBUSTION = 'stationary_combustion', 'Stationary Combustion'
        MOBILE_COMBUSTION = 'mobile_combustion', 'Mobile Combustion'
        PURCHASED_ELECTRICITY = 'purchased_electricity', 'Purchased Electricity'
        BUSINESS_TRAVEL_AIR = 'business_travel_air', 'Business Travel — Air'
        BUSINESS_TRAVEL_HOTEL = 'business_travel_hotel', 'Business Travel — Hotel'
        BUSINESS_TRAVEL_GROUND = 'business_travel_ground', 'Business Travel — Ground'
        PURCHASED_GOODS = 'purchased_goods', 'Purchased Goods & Services'

    class ReviewStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        FLAGGED = 'FLAGGED', 'Flagged'

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='records')
    source_record = models.OneToOneField(RawRecord, on_delete=models.CASCADE, related_name='normalized')

    # GHG Protocol classification
    scope = models.IntegerField(choices=Scope.choices)
    category = models.CharField(max_length=50, choices=Category.choices)

    # Where / who (plant code, meter ID, cost center, etc.)
    facility_id = models.CharField(max_length=100, blank=True)
    facility_name = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=300, blank=True)

    # Billing period — the actual dates from the source, NOT snapped to calendar months.
    # A utility bill covering 2024-01-03 to 2024-02-05 stays that way.
    period_start = models.DateField()
    period_end = models.DateField()

    # Raw activity exactly as it appeared in the source
    activity_quantity_raw = models.DecimalField(max_digits=18, decimal_places=4)
    activity_unit_raw = models.CharField(max_length=30)

    # Normalized activity (standard unit for this category)
    activity_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    activity_unit = models.CharField(max_length=20)

    # Emission factor snapshot — denormalized for audit stability
    emission_factor_value = models.DecimalField(max_digits=12, decimal_places=6)
    emission_factor_unit = models.CharField(max_length=50)   # e.g. 'kg CO2e/L'
    emission_factor_source = models.CharField(max_length=200)

    # Result
    co2e_kg = models.DecimalField(max_digits=18, decimal_places=4)

    # Analyst review state
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    reviewed_by = models.CharField(max_length=200, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    # Audit lock — set after analyst sign-off; prevents further edits
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.CharField(max_length=200, blank=True)

    # Automated quality flags — populated at parse time, visible to analyst
    flags = models.JSONField(default=list)   # list of human-readable warning strings
    is_suspicious = models.BooleanField(default=False, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-period_start', 'scope']
        indexes = [
            models.Index(fields=['tenant', 'review_status']),
            models.Index(fields=['tenant', 'scope']),
            models.Index(fields=['period_start', 'period_end']),
            models.Index(fields=['tenant', 'is_suspicious']),
        ]

    def __str__(self):
        return (
            f"{self.get_category_display()} | {self.co2e_kg:.1f} kg CO2e "
            f"| {self.period_start} | {self.review_status}"
        )


class AuditEvent(models.Model):
    """
    Append-only event log. Every state change on a NormalizedRecord or a
    DataIngestion must produce one of these. Never update or delete rows here.

    before_state / after_state capture the JSON diff so the full history of
    a record can be reconstructed without relying on the record's current state.
    """
    class EventType(models.TextChoices):
        INGESTION_STARTED = 'INGESTION_STARTED', 'Ingestion started'
        INGESTION_COMPLETE = 'INGESTION_COMPLETE', 'Ingestion complete'
        INGESTION_FAILED = 'INGESTION_FAILED', 'Ingestion failed'
        RECORD_CREATED = 'RECORD_CREATED', 'Record created'
        RECORD_REVIEWED = 'RECORD_REVIEWED', 'Record reviewed'
        RECORD_FLAGGED = 'RECORD_FLAGGED', 'Record flagged'
        RECORD_LOCKED = 'RECORD_LOCKED', 'Record locked'
        RECORD_EDITED = 'RECORD_EDITED', 'Record edited'
        BULK_REVIEW = 'BULK_REVIEW', 'Bulk review'

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='audit_events')
    record = models.ForeignKey(
        NormalizedRecord, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='audit_events'
    )
    ingestion = models.ForeignKey(
        DataIngestion, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='audit_events'
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    actor = models.CharField(max_length=200)
    timestamp = models.DateTimeField(auto_now_add=True)
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.event_type} by {self.actor} @ {self.timestamp:%Y-%m-%d %H:%M}"
