from django.contrib import admin
from apps.core.models import Tenant
from .models import DataIngestion, RawRecord, NormalizedRecord, EmissionFactor, AuditEvent


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'created_at']
    prepopulated_fields = {'slug': ('name',)}


@admin.register(DataIngestion)
class DataIngestionAdmin(admin.ModelAdmin):
    list_display = ['id', 'tenant', 'source_type', 'status', 'ingested_at', 'row_count', 'error_count']
    list_filter = ['source_type', 'status', 'tenant']
    readonly_fields = ['ingested_at', 'processing_log']


@admin.register(NormalizedRecord)
class NormalizedRecordAdmin(admin.ModelAdmin):
    list_display = ['id', 'tenant', 'scope', 'category', 'period_start', 'co2e_kg', 'review_status', 'is_suspicious', 'is_locked']
    list_filter = ['tenant', 'scope', 'review_status', 'is_suspicious', 'is_locked']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(EmissionFactor)
class EmissionFactorAdmin(admin.ModelAdmin):
    list_display = ['category', 'activity_unit', 'kg_co2e_per_unit', 'source', 'valid_from', 'valid_to']


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'actor', 'tenant', 'timestamp']
    readonly_fields = ['timestamp', 'before_state', 'after_state']
