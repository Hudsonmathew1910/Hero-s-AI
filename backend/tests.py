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
    def test_baymax_fallback(self, mock_client_class, mock_requests):
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
            self.assertEqual(halo.hf_token, "hf_test_token")
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
    def test_halo_fallback_routing(self, mock_client_class):
        """Test that Halo successfully falls back to Llama 3.3 when the primary model fails."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Primary call raises an exception, secondary fallback succeeds
        mock_client.chat_completion.side_effect = [
            Exception("Primary model service unavailable"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="Hello from Llama 3.3 fallback!"))])
        ]
        
        with patch.dict(os.environ, {"HF_TOKEN": "hf_test_token"}):
            halo = Halo()
            response = halo.handle_text("Hello")
            
            self.assertEqual(response, "Hello from Llama 3.3 fallback!")
            self.assertEqual(mock_client.chat_completion.call_count, 2)
            # Verify primary model was tried first
            mock_client.chat_completion.assert_any_call(
                model=Halo.PRIMARY_MODEL,
                messages=[
                    {"role": "system", "content": Halo.SYSTEM_PROMPT},
                    {"role": "user", "content": "Hello"}
                ],
                max_tokens=Halo.DEFAULT_MAX_TOKENS,
                temperature=Halo.DEFAULT_TEMPERATURE
            )
            # Verify fallback model was tried second
            mock_client.chat_completion.assert_called_with(
                model=Halo.FALLBACK_MODEL,
                messages=[
                    {"role": "system", "content": Halo.SYSTEM_PROMPT},
                    {"role": "user", "content": "Hello"}
                ],
                max_tokens=Halo.DEFAULT_MAX_TOKENS,
                temperature=Halo.DEFAULT_TEMPERATURE
            )
