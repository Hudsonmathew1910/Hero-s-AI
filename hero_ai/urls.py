# backend/urls.py

from django.contrib import admin
from django.urls import path, include
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
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)