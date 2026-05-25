from django.urls import path
from . import views

urlpatterns = [
    path('tenants/', views.tenant_list),
    path('ingestions/', views.ingestion_list),
    path('ingestions/upload/', views.upload_file),
    path('ingestions/<int:pk>/', views.ingestion_detail),
    path('records/', views.record_list),
    path('records/bulk-review/', views.bulk_review),
    path('records/<int:pk>/', views.record_detail),
    path('records/<int:pk>/review/', views.record_review),
    path('records/<int:pk>/audit/', views.record_audit),
    path('dashboard/', views.dashboard_stats),
]
