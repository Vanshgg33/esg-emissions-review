"""
Seeds a demo tenant and processes all three sample data files.
Run: python manage.py seed_data
"""
import os
from pathlib import Path
from django.core.management.base import BaseCommand
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.core.models import Tenant
from apps.ingestion.models import DataIngestion, NormalizedRecord


SAMPLE_DIR = Path(__file__).resolve().parents[4] / 'sample_data'


class Command(BaseCommand):
    help = 'Seed demo tenant and ingest sample data files'

    def handle(self, *args, **options):
        from apps.ingestion.views import _process_sap, _process_utility, _process_travel

        tenant, created = Tenant.objects.get_or_create(
            slug='cjp-corporation',
            defaults={'name': 'CJP Corporation'}
        )
        if created:
            self.stdout.write(f'Created tenant: {tenant.name}')
        else:
            self.stdout.write(f'Using existing tenant: {tenant.name}')

        sources = [
            ('sap_fuel_mm60.txt',    DataIngestion.SourceType.SAP_FUEL,            _process_sap),
            ('utility_portal.csv',   DataIngestion.SourceType.UTILITY_ELECTRICITY, _process_utility),
            ('travel_concur.csv',    DataIngestion.SourceType.TRAVEL,              _process_travel),
        ]

        for filename, source_type, processor in sources:
            # Idempotent: skip if this sample file was already ingested for this tenant
            if DataIngestion.objects.filter(tenant=tenant, original_filename=filename).exists():
                self.stdout.write(f'  Skipping {filename} — already seeded')
                continue

            filepath = SAMPLE_DIR / filename
            if not filepath.exists():
                self.stdout.write(self.style.WARNING(f'  Skipping {filename} — not found'))
                continue

            content = filepath.read_bytes()
            ingestion = DataIngestion.objects.create(
                tenant=tenant,
                source_type=source_type,
                status=DataIngestion.Status.PROCESSING,
                ingested_by='seed_script',
                original_filename=filename,
            )
            log = []
            try:
                processor(ingestion, tenant, content, log, 'seed_script')
                ingestion.status = DataIngestion.Status.COMPLETE
            except Exception as e:
                ingestion.status = DataIngestion.Status.FAILED
                log.append({'level': 'error', 'row': None, 'message': str(e)})
                self.stdout.write(self.style.ERROR(f'  {filename}: {e}'))

            ingestion.processing_log = log
            ingestion.save()
            self.stdout.write(
                f'  {filename}: {ingestion.row_count} rows, '
                f'{ingestion.error_count} errors, status={ingestion.status}'
            )

        total = NormalizedRecord.objects.filter(tenant=tenant).count()
        self.stdout.write(self.style.SUCCESS(f'\nDone. {total} normalized records for {tenant.name}.'))
        self.stdout.write('Create superuser: python manage.py createsuperuser')
