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
        # 2. Get web search context
        get_hist = getattr(self.baymax, "_get_limited_history", lambda x: self.baymax.chat_history)
        chat_history = get_hist("web_search")
        search_result, _ = perform_web_search(
            message,
            gemini_key=getattr(self.baymax, "gemini_key", "") or "",
            chat_history=chat_history
        )
        
        prompt = (
            f"{message}\n\n"
            f"[Search Result]\n{search_result}\n\n"
            f"Important: use search result also."
        )
        return self.baymax.handle_coding(prompt)

    def handle_search_file(self, message: str, files_data: list) -> str:
        """search and send result to LLM with file handling task"""
        get_hist = getattr(self.baymax, "_get_limited_history", lambda x: getattr(self.baymax, "chat_history", []))
        chat_history = get_hist("web_search")
        search_result, _ = perform_web_search(
            message,
            gemini_key=getattr(self.baymax, "gemini_key", "") or "",
            chat_history=chat_history
        )
        
        prompt = (
            f"{message}\n\n"
            f"[Search Result]\n{search_result}\n\n"
            f"Important: use search result also."
        )
        return self.baymax.handle_file(prompt, files_data)

    def handle_code_file(self, message: str, files_data: list) -> str:
        """file preprocessing and send result to LLM with new prompt file handling and coding prompt."""
        prompt = (
            f"{message}\n\n"
            f"Important: act as a coding assistant while handling these files."
        )
        return self.baymax.handle_file(prompt, files_data)

    def handle_search_code_file(self, message: str, files_data: list) -> str:
        """search + file preprocessing and send result to LLM with new prompt file handling with coding and search result prompt."""
        get_hist = getattr(self.baymax, "_get_limited_history", lambda x: getattr(self.baymax, "chat_history", []))
        chat_history = get_hist("web_search")
        search_result, _ = perform_web_search(
            message,
            gemini_key=getattr(self.baymax, "gemini_key", "") or "",
            chat_history=chat_history
        )
        
        prompt = (
            f"{message}\n\n"
            f"[Search Result]\n{search_result}\n\n"
            f"Important: use search result also and act as a coding assistant while handling these files."
        )
        return self.baymax.handle_file(prompt, files_data)

    def handle_voice_file(self, message: str, files_data: list) -> str:
        """file preprocessing and send result to LLM with new prompt for voice chat."""
        prompt = (
            f"User message: {message}\n\n"
            f"Important: The user has just attached a file to this message. The file content is attached natively. "
            f"Act as a helpful conversational assistant discussing this file. "
            f"Keep your response concise and conversational since this is a voice chat."
        )
        
        # Directly use native inline_data for voice files to prevent LLM hallucination and speed up response
        primary = self.baymax.models.get("voice_chat", "gemini-3.1-flash-lite")
        max_tok = self.baymax._TOKEN_BUDGETS.get("voice", 256)
        
        return self.baymax._with_fallback(
            primary_model=primary,
            text=prompt,
            max_tokens=max_tok,
            task="voice",
            current_files=files_data
        )
