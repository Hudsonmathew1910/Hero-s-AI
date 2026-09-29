import logging
from backend.models_task.web_search import perform_web_search

logger = logging.getLogger(__name__)

class MultipleTask:
    """
    Handles multiple task modes when selected manually by the user.
    Combinations:
    - search + code
    - search + file
    - code + file
    - search + code + file
    """
    def __init__(self, baymax):
        self.baymax = baymax

    def handle_search_code(self, message: str) -> str:
        """search and send result to LLM with code task"""
        # We rely on handle_coding's built-in query router
        return self.baymax.handle_coding(message)

    def handle_search_file(self, message: str, files_data: list) -> str:
        """search and send result to LLM with file handling task"""
        router_instruction = (
            "CRITICAL INSTRUCTION: If the user's query requires current, live, or real-time web data "
            "(like news, weather, live prices, or recent events that you don't know), "
            "you MUST NOT attempt to answer. Instead, output ONLY exactly this format: SEARCH_REQUIRED: [your optimized search query]. "
            "If the query does NOT require live data, answer it directly and normally."
        )
        enriched_text = f"{router_instruction}\n\nUser Message: {message}"
        response = self.baymax.handle_file(enriched_text, files_data)
        
        if response and "SEARCH_REQUIRED:" in response:
            search_query = response.split("SEARCH_REQUIRED:")[1].strip()
            # Perform search and run file handler again
            raw_context = perform_web_search(search_query)
            if raw_context:
                enriched_text2 = (
                    "System Instruction: Below is some retrieved Live Data related to the user query.\n"
                    "Use this Live Data and the attached files to answer accurately.\n\n"
                    f"Live Data:\n{raw_context}\n\n"
                    f"User Query: {message}"
                )
                return self.baymax.handle_file(enriched_text2, files_data)
        return response

    def handle_code_file(self, message: str, files_data: list) -> str:
        """file preprocessing and send result to LLM with new prompt file handling and coding prompt."""
        prompt = (
            f"{message}\n\n"
            f"Important: act as a coding assistant while handling these files."
        )
        return self.baymax.handle_file(prompt, files_data)

    def handle_search_code_file(self, message: str, files_data: list) -> str:
        """search + file preprocessing and send result to LLM with new prompt file handling with coding and search result prompt."""
        router_instruction = (
            "CRITICAL INSTRUCTION: If the user's query requires current, live, or real-time web data "
            "(like news, weather, live prices, or recent events that you don't know), "
            "you MUST NOT attempt to answer. Instead, output ONLY exactly this format: SEARCH_REQUIRED: [your optimized search query]. "
            "If the query does NOT require live data, answer it directly and normally."
        )
        prompt = (
            f"{router_instruction}\n\n"
            f"User message: {message}\n\n"
            f"Important: act as a coding assistant while handling these files."
        )
        response = self.baymax.handle_file(prompt, files_data)
        if response and "SEARCH_REQUIRED:" in response:
            search_query = response.split("SEARCH_REQUIRED:")[1].strip()
            raw_context = perform_web_search(search_query)
            if raw_context:
                enriched_text2 = (
                    "System Instruction: Below is some retrieved Live Data related to the user query.\n"
                    "Use this Live Data and the attached files to answer accurately.\n\n"
                    f"Live Data:\n{raw_context}\n\n"
                    f"User Query: {message}\n\n"
                    f"Important: act as a coding assistant while handling these files."
                )
                return self.baymax.handle_file(enriched_text2, files_data)
        return response

    def handle_voice_file(self, message: str, files_data: list) -> str:
        """file preprocessing and send result to LLM with new prompt for voice chat."""
        prompt = (
            f"User message: {message}\n\n"
            f"Important: The user has just attached a file to this message. The file content is attached natively. "
            f"Act as a helpful conversational assistant discussing this file. "
            f"Keep your response concise and conversational since this is a voice chat."
        )
        
        primary = self.baymax.models.get("voice_chat", "gemini-3.5-flash-lite")
        max_tok = self.baymax._TOKEN_BUDGETS.get("voice", 256)
        
        return self.baymax._with_fallback(
            primary_model=primary,
            text=prompt,
            max_tokens=max_tok,
            task="voice",
            current_files=files_data
        )

    def handle_voice_search(self, message: str) -> str:
        """search and send result to LLM with voice chat response constraints"""
        # Voice chat uses handle_voice_chat internally for routing now
        return self.baymax.handle_voice_chat(message)

    def handle_voice_search_file(self, message: str, files_data: list) -> str:
        """search + file preprocessing and send result to LLM with voice chat constraints"""
        router_instruction = (
            "CRITICAL INSTRUCTION: If the user's query requires current, live, or real-time web data "
            "(like news, weather, live prices, or recent events that you don't know), "
            "you MUST NOT attempt to answer. Instead, output ONLY exactly this format: SEARCH_REQUIRED: [your optimized search query]. "
            "If the query does NOT require live data, answer it directly and normally."
        )
        prompt = (
            f"{router_instruction}\n\n"
            f"User message: {message}\n\n"
            f"Important: Keep your response extremely brief, casual, and natural (max 2-3 short sentences, under 60 words total) since this is a voice chat. Do not output lists or bullets."
        )
        
        primary = self.baymax.models.get("voice_chat", "gemini-3.5-flash-lite")
        max_tok = self.baymax._TOKEN_BUDGETS.get("voice", 256)
        
        response = self.baymax._with_fallback(
            primary_model=primary,
            text=prompt,
            max_tokens=max_tok,
            task="voice",
            current_files=files_data
        )
        
        if response and "SEARCH_REQUIRED:" in response:
            search_query = response.split("SEARCH_REQUIRED:")[1].strip()
            raw_context = perform_web_search(search_query)
            if raw_context:
                enriched_text2 = (
                    "System Instruction: Below is some retrieved Live Data related to the user query.\n"
                    "Use this Live Data and the attached files to answer accurately.\n\n"
                    f"Live Data:\n{raw_context}\n\n"
                    f"User Query: {message}\n\n"
                    f"Important: Keep your response extremely brief, casual, and natural (max 2-3 short sentences, under 60 words total) since this is a voice chat. Do not output lists or bullets."
                )
                return self.baymax._with_fallback(
                    primary_model=primary,
                    text=enriched_text2,
                    max_tokens=max_tok,
                    task="voice",
                    current_files=files_data
                )
        return response
