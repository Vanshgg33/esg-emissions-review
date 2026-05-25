from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.http import FileResponse, HttpResponse


def serve_react(request, *args, **kwargs):
    index = settings.BASE_DIR / 'staticfiles' / 'index.html'
    if index.exists():
        return FileResponse(open(index, 'rb'), content_type='text/html')
    return HttpResponse(
        '<p>Frontend not built. Run <code>npm run build</code> in the frontend directory, '
        'then <code>python manage.py collectstatic</code>.</p>',
        status=503,
    )


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('apps.ingestion.urls')),
    re_path(r'^(?!api/)(?!admin/)(?!static/)(?!media/).*$', serve_react),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
