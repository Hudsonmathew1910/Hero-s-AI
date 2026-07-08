from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='zuno_index'),
    path('process_audio/', views.process_audio, name='zuno_process_audio'),
]
