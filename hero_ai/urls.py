# backend/urls.py

from django.contrib import admin
from django.urls import path, include, re_path
from backend import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('landing/', views.landing, name='landing'),
    path('', include('backend.urls')),
    path('infinsight/', include('infinsight.urls')),
    path('zuno/', include('zuno.urls')),
    
    # Catch-all pattern to force custom 404 even in DEBUG mode (excluding admin so APPEND_SLASH still works)
    re_path(r'^(?!admin(?:/|$)).*$', views.custom_404),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler404 = 'backend.views.custom_404'