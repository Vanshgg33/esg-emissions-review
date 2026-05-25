from rest_framework import serializers
from apps.core.models import Tenant
from .models import DataIngestion, RawRecord, NormalizedRecord, AuditEvent


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ['id', 'name', 'slug', 'created_at']


class DataIngestionSerializer(serializers.ModelSerializer):
    source_type_display = serializers.CharField(source='get_source_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta:
        model = DataIngestion
        fields = [
            'id', 'tenant', 'tenant_name', 'source_type', 'source_type_display',
            'status', 'status_display', 'ingested_at', 'ingested_by',
            'original_filename', 'row_count', 'error_count', 'warning_count',
            'processing_log',
        ]


class NormalizedRecordSerializer(serializers.ModelSerializer):
    scope_display = serializers.CharField(source='get_scope_display', read_only=True)
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    review_status_display = serializers.CharField(source='get_review_status_display', read_only=True)
    source_type = serializers.CharField(
        source='source_record.ingestion.source_type', read_only=True
    )
    ingestion_id = serializers.IntegerField(
        source='source_record.ingestion.id', read_only=True
    )
    raw_data = serializers.JSONField(source='source_record.raw_data', read_only=True)
    parse_warnings = serializers.JSONField(source='source_record.parse_errors', read_only=True)
    tenant_name = serializers.CharField(source='tenant.name', read_only=True)

    class Meta:
        model = NormalizedRecord
        fields = [
            'id', 'tenant', 'tenant_name',
            'scope', 'scope_display', 'category', 'category_display',
            'facility_id', 'facility_name', 'description',
            'period_start', 'period_end',
            'activity_quantity_raw', 'activity_unit_raw',
            'activity_quantity', 'activity_unit',
            'emission_factor_value', 'emission_factor_unit', 'emission_factor_source',
            'co2e_kg',
            'review_status', 'review_status_display',
            'reviewed_by', 'reviewed_at', 'review_notes',
            'is_locked', 'locked_at', 'locked_by',
            'flags', 'is_suspicious',
            'created_at', 'updated_at',
            'source_type', 'ingestion_id', 'raw_data', 'parse_warnings',
        ]


class AuditEventSerializer(serializers.ModelSerializer):
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            'id', 'event_type', 'event_type_display', 'actor',
            'timestamp', 'before_state', 'after_state', 'note',
        ]
