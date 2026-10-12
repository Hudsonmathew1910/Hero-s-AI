from django.urls import path
from . import views
from . import developer_api
from . import platform_views

urlpatterns = [
    # Home
    path('', views.home, name='home'),
    
    # Privacy Policy & Terms
    path('privacy', views.privacy_view, name='privacy'),
    path('terms', views.privacy_view, name='terms'),
    
    # Developer Platform UI
    path('platform/', views.platform_view, name='platform'),
    
    # Email/Password Authentication
    path('api/auth/signup', views.signup_view, name='signup'),
    path('api/auth/login', views.login_view, name='login'),
    path('api/auth/logout', views.logout_view, name='logout'),
    path('api/auth/check-session', views.check_session, name='check_session'),
    
    # Google OAuth
    path('auth/google', views.google_login, name='google_login'),
    path('auth/google/callback', views.google_callback, name='google_callback'),
    path('api/auth/google/complete-signup', views.complete_google_signup, name='complete_google_signup'),
    
    # API Keys
    path('api/keys/save', views.save_api_keys, name='save_api_keys'),
    path('api/keys/check', views.check_api_keys, name='check_api_keys'),
    
    # Chat & TTS & STT
    path('api/chat', views.chat_api, name='chat_api'),
    path('api/chat/abort', views.abort_chat_api, name='abort_chat_api'),
    path('api/tts', views.tts_api, name='tts_api'),
    path('api/transcribe', views.transcribe_audio, name='transcribe_audio'),
    path('api/chat/history', views.get_chat_history, name='get_chat_history'),
    path('api/chat/history/<uuid:chat_id>', views.get_chat_messages, name='get_chat_messages'),
    path('api/chat/history/<uuid:chat_id>/delete', views.delete_chat, name='delete_chat'),
    path('api/chat/history/<uuid:chat_id>/recent', views.get_recent_messages, name='get_recent_messages'),
    
    # Profile & Settings
    path('api/user/profile', views.get_user_profile, name='get_user_profile'),
    path('api/user/settings', views.save_user_settings, name='save_user_settings'),        # ← ADD THIS
    path('api/user/settings/save', views.save_user_settings, name='save_user_settings_alt'), # keep old if needed
    
    # Developer API
    path('api/v1/chat/completions', developer_api.developer_chat_completions, name='developer_chat_completions'),
    path('api/v1/usage', developer_api.developer_usage, name='developer_usage'),
    path('api/v1/models', developer_api.developer_models, name='developer_models'),
    
    # Platform Dashboard & Keys
    path('api/platform/keys/generate', platform_views.generate_api_key, name='platform_generate_key'),
    path('api/platform/keys/list', platform_views.list_api_keys, name='platform_list_keys'),
    path('api/platform/keys/toggle/<str:key_hash>', platform_views.toggle_api_key_status, name='platform_toggle_key'),
    path('api/platform/keys/delete/<str:key_hash>', platform_views.delete_api_key, name='platform_delete_key'),
    path('api/platform/keys/external', platform_views.save_external_keys, name='platform_save_external_keys'),
    path('api/platform/keys/external/get', platform_views.get_external_keys, name='platform_get_external_keys'),
    path('api/platform/keys/test', platform_views.test_external_key, name='platform_test_external_key'),
    path('api/platform/usage', platform_views.get_platform_usage, name='platform_get_usage'),
    path('api/platform/help/send', platform_views.send_help_email, name='platform_send_email'),
    path('api/platform/quota/increase', platform_views.request_quota_increase, name='platform_quota_increase'),
    path('api/platform/projects/create', platform_views.create_project, name='platform_create_project'),
    path('api/platform/projects/list', platform_views.list_projects, name='platform_list_projects'),
    path('api/platform/projects/delete/<str:project_id>', platform_views.delete_project, name='platform_delete_project'),
    path('api/user/password/change', platform_views.change_password, name='platform_change_password'),
    path('api/user/danger/purge-logs', platform_views.purge_request_logs, name='platform_purge_logs'),
    path('api/user/danger/delete-account', platform_views.delete_developer_account, name='platform_delete_account'),
]