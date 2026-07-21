import json
import os
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.core.exceptions import ImproperlyConfigured
from backend.Nlp import get_intent
from backend.hero_model import Baymax

# Import Halo and client to ensure module is loaded and patches attach correctly
from backend.halo import Halo

class NlpTests(TestCase):
    def test_get_intent_direct(self):
        """Test rule-based intent parsing directly using Nlp's get_intent."""
        self.assertEqual(get_intent("play some music"), "play_song")
        self.assertEqual(get_intent("write python code to reverse a list"), "coding")
        self.assertEqual(get_intent("search for the latest news"), "web_search")
        self.assertEqual(get_intent("remind me to complete work at 5pm"), "task")
        self.assertEqual(get_intent("ok"), "chat")

class HeroModelTests(TestCase):
    @patch('backend.hero_model.requests.post')
    @patch('google.genai.Client')
    @patch('backend.hero_model.Baymax._enrich_with_web_search')
    def test_baymax_fallback(self, mock_enrich, mock_client_class, mock_requests):
        mock_enrich.side_effect = lambda text, task: text
        # Mock Gemini Client to raise an exception
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Gemini quota exceeded")
        mock_client_class.return_value = mock_client
        
        # Mock OpenRouter to succeed
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from OpenRouter!"}}]
        }
        mock_requests.return_value = mock_response
        
        baymax = Baymax(
            gemini_key="test-key",
            openrouter_key="test-key",
            chat_history=[]
        )
        
        response = baymax.handle_text("Hello")
        
        self.assertEqual(response, "Hello from OpenRouter!")
        self.assertTrue(mock_requests.called)

class HaloModelTests(TestCase):
    def test_halo_init_missing_token(self):
        """Test that Halo initialization raises ImproperlyConfigured when HF_TOKEN is missing."""
        # Temporarily hide HF_TOKEN from environment if set
        with patch.dict(os.environ, {}, clear=True):
            if "HF_TOKEN" in os.environ:
                del os.environ["HF_TOKEN"]
            with self.assertRaises(ImproperlyConfigured):
                Halo()

    @patch('backend.halo.InferenceClient')
    def test_halo_init_success(self, mock_client):
        """Test that Halo initializes successfully when HF_TOKEN is present."""
        with patch.dict(os.environ, {"HF_TOKEN": "hf_test_token"}):
            halo = Halo()
            self.assertTrue(len(halo.clients) > 0)
            self.assertTrue(mock_client.called)

    def test_parse_smart_output(self):
        """Test JSON smart parsing helper under various outputs."""
        with patch.dict(os.environ, {"HF_TOKEN": "hf_test_token"}):
            with patch('backend.halo.InferenceClient'):
                halo = Halo()
                
                # Test plain text
                self.assertEqual(halo.parse_smart_output("Hello there"), "Hello there")
                
                # Test raw valid JSON
                json_raw = '{"status": "play_extension", "url": "https://youtube.com/watch?v=123"}'
                parsed = halo.parse_smart_output(json_raw)
                self.assertIsInstance(parsed, dict)
                self.assertEqual(parsed["status"], "play_extension")
                
                # Test JSON wrapped in markdown code blocks
                json_md = '```json\n{"status": "yt_control", "command": "pause"}\n```'
                parsed_md = halo.parse_smart_output(json_md)
                self.assertIsInstance(parsed_md, dict)
                self.assertEqual(parsed_md["command"], "pause")
                
                # Test invalid JSON starting with '{'
                self.assertEqual(halo.parse_smart_output("{not valid json}"), "{not valid json}")

    @patch('backend.halo.InferenceClient')
    @patch('backend.halo.Halo._enrich_with_web_search')
    def test_halo_fallback_routing(self, mock_enrich, mock_client_class):
        """Test that Halo successfully falls back to Llama 3.3 when the primary model fails."""
        mock_enrich.side_effect = lambda text: text
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Primary call raises an exception, secondary fallback succeeds
        mock_client.chat_completion.side_effect = [
            Exception("Primary model service unavailable"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="Hello from Llama 3.3 fallback!"))])
        ]
        
        with patch.dict(os.environ, {"HF_TOKEN": "hf_test_token"}, clear=True):
            halo = Halo()
            response = halo.handle_text("Hello")
            
            self.assertEqual(response, "Hello from Llama 3.3 fallback!")
            self.assertEqual(mock_client.chat_completion.call_count, 2)
            # Verify primary model was tried first
            mock_client.chat_completion.assert_any_call(
                model=Halo.PRIMARY_MODEL,
                messages=[
                    {"role": "system", "content": Halo.TEXT_PROMPT},
                    {"role": "user", "content": "Hello"}
                ],
                max_tokens=Halo.DEFAULT_MAX_TOKENS,
                temperature=Halo.DEFAULT_TEMPERATURE
            )
            # Verify fallback model was tried second
            mock_client.chat_completion.assert_called_with(
                model=Halo.FALLBACK_MODEL,
                messages=[
                    {"role": "system", "content": Halo.TEXT_PROMPT},
                    {"role": "user", "content": "Hello"}
                ],
                max_tokens=Halo.DEFAULT_MAX_TOKENS,
                temperature=Halo.DEFAULT_TEMPERATURE
            )


class HeroModelFastRoutingTests(TestCase):
    @patch('backend.hero_model.Baymax._call_groq')
    @patch('backend.hero_model.Baymax._with_fallback')
    def test_fast_route_provider_error(self, mock_fallback, mock_call_groq):
        """Test that a GroqProviderError on the first model immediately falls back to normal fallbacks."""
        from backend.hero_model import GroqProviderError
        from backend.fast import run_fast_route
        
        mock_call_groq.side_effect = GroqProviderError("Rate limit / traffic exceeded")
        mock_fallback.return_value = "Fallback Response"
        
        baymax = Baymax(
            gemini_key="gemini-key",
            openrouter_key="or-key",
            groq_key="groq-key",
            chat_history=[]
        )
        baymax.is_fast = True
        
        response = run_fast_route(baymax, "Hello", max_tokens=100, task="text_chat")
        
        self.assertEqual(response, "Fallback Response")
        self.assertEqual(mock_call_groq.call_count, 1)  # Only the first model was tried
        mock_fallback.assert_called_once_with('gemini-3.1-flash-lite', "Hello", 100, "fallback", "text_chat")

    @patch('backend.hero_model.Baymax._call_groq')
    @patch('backend.hero_model.Baymax._with_fallback')
    def test_fast_route_model_error(self, mock_fallback, mock_call_groq):
        """Test that a GroqModelError on the first model allows sequential try of the remaining Groq models."""
        from backend.hero_model import GroqModelError
        from backend.fast import run_fast_route
        
        mock_call_groq.side_effect = [
            GroqModelError("Model not found"),
            "Hello from second Groq model!"
        ]
        
        baymax = Baymax(
            gemini_key="gemini-key",
            openrouter_key="or-key",
            groq_key="groq-key",
            chat_history=[]
        )
        baymax.is_fast = True
        
        response = run_fast_route(baymax, "Hello", max_tokens=100, task="text_chat")
        
        self.assertEqual(response, "Hello from second Groq model!")
        self.assertEqual(mock_call_groq.call_count, 2)  # First failed, second succeeded
        self.assertFalse(mock_fallback.called)  # No need for fallback


class HaloUsageLimitTests(TestCase):
    def setUp(self):
        from backend.usage_tracker import STATS_FILE
        self.stats_file = STATS_FILE
        if os.path.exists(self.stats_file):
            try:
                os.remove(self.stats_file)
            except Exception:
                pass

    def tearDown(self):
        if os.path.exists(self.stats_file):
            try:
                os.remove(self.stats_file)
            except Exception:
                pass

    def test_increment_and_check_usage(self):
        from backend.usage_tracker import get_halo_usage, increment_halo_usage
        user_key = "test_user_key"
        self.assertEqual(get_halo_usage(user_key), 0)
        
        increment_halo_usage(user_key)
        self.assertEqual(get_halo_usage(user_key), 1)
        
        increment_halo_usage(user_key)
        self.assertEqual(get_halo_usage(user_key), 2)

    @patch('backend.halo.InferenceClient')
    def test_chat_api_halo_limit_enforced(self, mock_client_class):
        from django.test import Client
        from backend.usage_tracker import HALO_MAX_LIMIT, increment_halo_usage
        
        client = Client()
        
        # Initialize session to obtain session_key
        session = client.session
        session.save()
        session_key = session.session_key
        user_key = f"anon_{session_key}"
        
        # Increment to max limit
        for _ in range(HALO_MAX_LIMIT):
            increment_halo_usage(user_key)
            
        # Send query to chat_api
        response = client.post(
            '/api/chat',
            data=json.dumps({
                'message': 'Hello Halo',
                'model': 'Halo',
                'mode': 'text',
                'session_id': 'test_session',
            }),
            content_type='application/json',
            HTTP_X_SESSION_ID='test_session'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("maximum message limit for Halo", data.get("reply", ""))

    def test_chat_api_halo_blocked_features(self):
        from django.test import Client
        client = Client()
        
        # Request coding mode which should be blocked immediately
        response = client.post(
            '/api/chat',
            data=json.dumps({
                'message': 'Write python code to compute fibonacci',
                'model': 'Halo',
                'mode': 'coding',
                'session_id': 'test_session_coding',
            }),
            content_type='application/json',
            HTTP_X_SESSION_ID='test_session_coding'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Access Restricted", data.get("reply", ""))
        self.assertIn("coding or file handling features in Halo", data.get("reply", ""))

    def test_baymax_limit_enforced(self):
        from django.test import Client
        from backend.usage_tracker import BAYMAX_MAX_LIMIT, increment_baymax_usage
        
        client = Client()
        session = client.session
        session.save()
        session_key = session.session_key
        user_key = f"anon_{session_key}"
        
        # Increment Baymax usage to maximum limit
        for _ in range(BAYMAX_MAX_LIMIT):
            increment_baymax_usage(user_key)
            
        # Send query to chat_api for Baymax
        response = client.post(
            '/api/chat',
            data=json.dumps({
                'message': 'Hello Baymax',
                'model': 'Baymax',
                'mode': 'text',
                'session_id': 'test_session_baymax',
            }),
            content_type='application/json',
            HTTP_X_SESSION_ID='test_session_baymax'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("maximum message limit for Baymax", data.get("reply", ""))

