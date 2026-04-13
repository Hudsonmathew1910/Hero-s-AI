from django.urls import path
from . import views

urlpatterns = [
    # Home
    path('', views.home, name='home'),
    
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
    
    # Chat
    path('api/chat', views.chat_api, name='chat_api'),
    path('api/chat/history', views.get_chat_history, name='get_chat_history'),
    path('api/chat/history/<uuid:chat_id>', views.get_chat_messages, name='get_chat_messages'),
    path('api/chat/history/<uuid:chat_id>/delete', views.delete_chat, name='delete_chat'),
    path('api/chat/history/<uuid:chat_id>/recent', views.get_recent_messages, name='get_recent_messages'),
    
    # Profile & Settings
    path('api/user/profile', views.get_user_profile, name='get_user_profile'),
    path('api/user/settings', views.save_user_settings, name='save_user_settings'),        # ← ADD THIS
    path('api/user/settings/save', views.save_user_settings, name='save_user_settings_alt'), # keep old if needed
]