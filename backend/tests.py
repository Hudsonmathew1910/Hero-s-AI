import json
from unittest.mock import patch, MagicMock
from django.test import TestCase
from backend.Nlp import intent_parser
from backend.hero_model import Baymax

class NlpTests(TestCase):
    @patch('backend.Nlp.genai.GenerativeModel')
    def test_intent_parser(self, mock_model_class):
        mock_model = MagicMock()
        mock_model.generate_content.return_value.text = json.dumps({"mode": "websearch"})
        mock_model_class.return_value = mock_model
        
        mode = intent_parser("Who won the 2024 olympics?", "gemini-api-key")
        self.assertEqual(mode, "websearch")
        
        mock_model.generate_content.return_value.text = json.dumps({"mode": "text"})
        mode = intent_parser("Hello, how are you?", "gemini-api-key")
        self.assertEqual(mode, "text")

class HeroModelTests(TestCase):
    @patch('backend.hero_model.requests.post')
    @patch('backend.hero_model.genai.GenerativeModel')
    def test_baymax_fallback(self, mock_gemini, mock_requests):
        # Mock Gemini to raise an exception
        mock_gemini.side_effect = Exception("Gemini quota exceeded")
        
        # Mock OpenRouter to succeed
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from OpenRouter!"}}]
        }
        mock_requests.return_value = mock_response
        
        baymax = Baymax()
        keys = {"gemini": "test-key", "openrouter": "test-key"}
        
        response = baymax.dispatch(
            user_msg="Hello",
            history=[],
            keys=keys,
            task="text",
            primary_model="gemini-2.5-flash"
        )
        
        self.assertEqual(response, "Hello from OpenRouter!")
        self.assertTrue(mock_requests.called)
