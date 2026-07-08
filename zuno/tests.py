import os
from unittest.mock import patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from backend.models import User, Api
from backend.encryption import encrypt_api_key
from zuno.views import get_groq_client

class ZunoGroqClientTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        # Create a test user
        self.user = User.objects.create(
            name="Test User",
            email="testuser@example.com",
            password_hash="hashed_password"
        )
        
    def _add_session(self, request, user_id=None):
        """Helper to attach session middleware and set user_id."""
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        if user_id:
            request.session['user_id'] = str(user_id)
        request.session.save()

    @patch.dict(os.environ, {"GROQ_API_KEY": "env-key-123"})
    def test_anonymous_no_fallback_to_env(self):
        """Test that anonymous requests do NOT fall back to environment variable."""
        request = self.factory.post('/zuno/process_audio/')
        self._add_session(request, user_id=None) # Anonymous
        
        client = get_groq_client(request)
        self.assertIsNone(client)

    @patch.dict(os.environ, {}, clear=True)
    def test_no_key_returns_none(self):
        """Test that if no key is in DB, get_groq_client returns None."""
        request = self.factory.post('/zuno/process_audio/')
        self._add_session(request, user_id=None)
        
        client = get_groq_client(request)
        self.assertIsNone(client)

    @patch.dict(os.environ, {}, clear=True)
    def test_authenticated_user_database_key(self):
        """Test that an authenticated user loads their Groq key from the database."""
        # Save a Groq key for this user in DB
        Api.objects.create(
            user=self.user,
            model_name="Groq",
            api_key_encrypted=encrypt_api_key("db-groq-key")
        )
        
        request = self.factory.post('/zuno/process_audio/')
        self._add_session(request, user_id=self.user.user_id)
        
        client = get_groq_client(request)
        self.assertIsNotNone(client)
        self.assertEqual(client.api_key, "db-groq-key")

    @patch.dict(os.environ, {"GROQ_API_KEY": "env-fallback-key"})
    def test_authenticated_user_no_fallback_to_env(self):
        """Test that an authenticated user without a database key does NOT fall back to environment."""
        # No Api object created in DB
        request = self.factory.post('/zuno/process_audio/')
        self._add_session(request, user_id=self.user.user_id)
        
        client = get_groq_client(request)
        self.assertIsNone(client)
