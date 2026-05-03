from unittest.mock import patch, MagicMock
from django.test import TestCase
from infinsight.Rag import get_session_title

class RagTests(TestCase):
    @patch('infinsight.Rag.genai.GenerativeModel')
    def test_get_session_title(self, mock_model_class):
        mock_model = MagicMock()
        mock_model.generate_content.return_value.text = "Financial Report Q3"
        mock_model_class.return_value = mock_model
        
        title = get_session_title("finance_q3.csv", "csv", "test-key")
        self.assertEqual(title, "Financial Report Q3")
        
        mock_model.generate_content.side_effect = Exception("API error")
        title_fallback = get_session_title("data.pdf", "pdf", "test-key")
        self.assertEqual(title_fallback, "data.pdf")
