"""infinsight/urls.py"""

from django.urls import path
from . import views

urlpatterns = [
    # Main page
    path("", views.infinsight_page, name="infinsight_home"),

    # File upload + session creation
    path("upload/", views.upload_file, name="infinsight_upload"),

    # Chat
    path("chat/", views.chat, name="infinsight_chat"),

    # Session list
    path("sessions/", views.list_sessions, name="infinsight_sessions"),

    # Session detail (chat history)
    path("session/<uuid:session_id>/", views.session_detail, name="infinsight_session_detail"),

    # Session status polling
    path("session/<uuid:session_id>/status/", views.session_status, name="infinsight_session_status"),

    # Session deletion
    path("session/<uuid:session_id>/delete/", views.delete_session, name="infinsight_session_delete"),
]