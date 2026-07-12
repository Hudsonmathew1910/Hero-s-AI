from unittest.mock import patch, MagicMock
from django.test import TestCase
from infinsight.Rag import get_session_title

class RagTests(TestCase):
    @patch('google.genai.Client')
    def test_get_session_title(self, mock_client_class):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = "Financial Report Q3"
        mock_client_class.return_value = mock_client
        
        title = get_session_title("finance_q3.csv", "csv", "test-key")
        self.assertEqual(title, "Financial Report Q3")
        
        mock_client.models.generate_content.side_effect = Exception("API error")
        title_fallback = get_session_title("data.pdf", "pdf", "test-key")
        self.assertEqual(title_fallback, "data")

