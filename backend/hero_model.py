"""
hero_model.py — Baymax AI handler

Changes from original:
  • Structured logging via Python's `logging` module (replaces bare print calls)
  • Temporary-chat support: callers pass `temporary=True` to skip history persistence
  • Error handling helpers: _safe_error() returns full details to superusers, a generic
    message to everyone else
  • No existing public handler signatures were changed — all additions are backward-compatible
"""

import logging
import requests
import time

from backend.models_task.web_search import perform_web_search
from backend.Nlp import PreprocessedInput

# ---------------------------------------------------------------------------
# Module-level logger — attach handlers in Django settings / logging config
# ---------------------------------------------------------------------------
logger = logging.getLogger("hero_ai.baymax")


class Baymax:
    # ── System prompt constants (unchanged) ──────────────────────────────────

    BASIC_RULES = """You are Baymax, an LLM-powered AI assistant with multi-model capabilities.
                    Core Rules:
                    - Your name is Baymax.
                    - You are NOT a movie character. (Very Important)
                    - You are NOT a personal healthcare companion. (Very Important)
                    - You are a professional AI assistant similar to ChatGPT/Gemini(Don't mention in response).
                    - Always respond in a natural, human-like, friendly tone.
                    - Be clear, helpful, and practical.

                    Capabilities:
                    - You can handle coding and programming tasks when required.
                    - You can search and provide information using web search.
                    - You can analyze text-based files using file handling. (read directly from the file)
                    - You can engage in natural voice-style conversations.

                    Identity Handling:
                    - If asked "What is your name?" → Say: "I'm Baymax, an AI assistant."
                    - If asked "Who is Baymax?" → First say you are an AI assistant, then clarify:
                    "Baymax is also a character from Big Hero 6, but here I’m an AI assistant designed to help you."""

    TEXT_PROMPT = """You are Baymax, a friendly AI assistant for text conversations.
                    Rules:
                    - Be warm, natural, and engaging.
                    - Explain things in simple, easy-to-understand language.
                    - Focus on helpful, real-world advice.
                    - Keep responses clear and conversational.
                    - Ask follow-up questions when helpful."""

    CODING_PROMPT = """You are Baymax, an expert programmer and coding mentor.
                        Rules:
                        - Provide correct, clean, and efficient code.
                        - Use beginner-friendly explanations.
                        - Add comments for complex logic.
                        - Show example usage and expected output.
                        - Suggest best practices and improvements.
                        - Keep explanations clear and structured."""

    VOICE_PROMPT = """You are Baymax, a voice assistant.
                        Rules:
                        - Keep responses short and natural.
                        - Sound like a real human conversation.
                        - Avoid long explanations.
                        - Be friendly, casual, and quick."""

    WEB_SEARCH_PROMPT = """You are Baymax, a research assistant with web access.
                        Rules:
                        - Provide accurate and up-to-date information.
                        - Base responses only on given search results.
                        - Summarize clearly and concisely.
                        - Highlight key insights.
                        - Avoid unnecessary details."""

    _TOKEN_BUDGETS = {
        "text_chat":      1000,
        "coding":         2000,
        "voice":          200,
        "web_search":     800,
        "file_analysis":  4000,
    }

    # ── Constructor ───────────────────────────────────────────────────────────

    def __init__(
        self,
        gemini_key:       str | None = None,
        openrouter_key:   str | None = None,
        groq_key:         str | None = None,
        user_instruction: str | None = None,
        user_about_me:    str | None = None,
        chat_history:     list | None = None,
        user_name:        str | None = None,
        nlp_result:       "PreprocessedInput | None" = None,
        # ── NEW: temporary chat flag ─────────────────────────────────────────
        temporary:        bool = False,
        # ── NEW: is the calling user a superuser? (for error detail level) ───
        is_superuser:     bool = False,
    ):
        self.gemini_key       = gemini_key
        self.openrouter_key   = openrouter_key
        self.groq_key         = groq_key
        self.user_instruction = user_instruction or ""
        self.user_about_me    = user_about_me    or ""
        self.user_name        = user_name        or ""
        self.nlp_result       = nlp_result       or {}

        # Temporary chat: if True, chat_history is intentionally empty and
        # the caller (views.py) must skip persistence after getting the reply.
        self.temporary        = temporary
        self.chat_history     = [] if temporary else (chat_history or [])

        # Controls whether _safe_error() reveals internal details
        self.is_superuser     = is_superuser

        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.groq_url       = "https://api.groq.com/openai/v1/chat/completions"

        self.models = {
            'text_chat':       'nvidia/nemotron-3-nano-30b-a3b:free',
            'voice_chat':      'gemini-2.5-flash-lite',
            'file_analysis':   'gemini-2.5-flash',
            'coding':          'gemini-2.5-flash-lite',
            'live_screen':     'gemini-2.5-flash',
            'task_automation': 'nvidia/nemotron-3-super-120b-a12b:free',
            'web_search':      'nvidia/nemotron-3-nano-30b-a3b:free',
            'web_search_preprocessor':      'meta-llama/llama-3.3-70b:free',
            'fallback': [
                'google/gemma-4-26b-a4b-it:free',
                'google/gemma-4-31b-it:free',
                # 'mistralai/mistral-small-3.1-24b-instruct:free',
                'meta-llama/llama-3.3-70b-instruct:free',
                'meta-llama/llama-3.2-3b-instruct:free',
                'nvidia/nemotron-nano-9b-v2:free',
                # 'stepfun/step-3.5-flash:free',
            ],
            'fallback_with_groq': [
                "llama-3.1-8b-instant",
                "qwen-3-32b",
                "llama-3.3-70b-versatile",
                "kimi-k2",
            ],
        }

        logger.debug(
            "Baymax initialised | temporary=%s | superuser=%s | raw_history_len=%d",
            self.temporary, self.is_superuser, len(self.chat_history),
        )

    # =========================================================================
    # ERROR HANDLING HELPERS
    # =========================================================================

    def _safe_error(self, exc: Exception, context: str = "") -> str:
        """
        Return an error string whose verbosity depends on the caller's role.

        • Superusers  → full traceback / exception details so they can debug.
        • Normal users → a polite, non-leaking message.

        All errors are always written to the logger at ERROR level regardless
        of what is shown to the user.
        """
        import traceback
        tb = traceback.format_exc()
        logger.error(
            "Baymax error [%s]: %s\n%s",
            context or "unknown", exc, tb,
        )

        if self.is_superuser:
            # Full internal details — only visible to admins
            return (
                f"**[Superuser Debug]** Error in `{context}`:\n\n"
                f"```\n{tb.strip()}\n```"
            )

        # Generic safe message for regular users
        return "Something went wrong. Please try again later."

    # =========================================================================
    # NLP HELPERS (unchanged)
    # =========================================================================

    def _nlp_meta(self) -> dict:
        """Return the NLP metadata dict safely."""
        return self.nlp_result.get("metadata", {}) if self.nlp_result else {}

    def _smart_token_budget(self, task: str) -> int:
        """Return a token budget for the task, reduced for short/simple messages."""
        base = self._TOKEN_BUDGETS.get(task, 500)
        meta = self._nlp_meta()

        if not meta:
            return base

        if meta.get("is_short") and not meta.get("has_code_block"):
            if task in ("text_chat", "voice"):
                return max(100, base // 2)

        if meta.get("has_code_block") and task == "text_chat":
            return max(base, self._TOKEN_BUDGETS["coding"])

        return base

    def _enrich_system_prompt(self, base_prompt: str) -> str:
        """Append NLP-derived behavioural hints to the system prompt."""
        meta = self._nlp_meta()
        if not meta:
            return base_prompt

        hints = []
        if meta.get("is_short") and not meta.get("has_code_block"):
            hints.append("short conversational reply preferred")
        if meta.get("has_question"):
            hints.append("the user is asking a question — answer it directly")
        if meta.get("has_code_block"):
            hints.append("the user included code — focus on code in your reply")
        if meta.get("has_url"):
            hints.append("the user referenced a URL — acknowledge it in your reply")

        if hints:
            base_prompt += f"\n\n[Response hint: {'; '.join(hints)}]"

        return base_prompt

    # =========================================================================
    # PROMPT BUILDERS (unchanged)
    # =========================================================================

    def _build_system_prompt(self, task: str) -> str:
        """Select and build the system prompt for the given task."""
        if task == "coding":
            prompt = self.CODING_PROMPT
        elif task == "voice":
            prompt = self.VOICE_PROMPT
        elif task == "web_search":
            prompt = self.WEB_SEARCH_PROMPT
        else:
            prompt = self.TEXT_PROMPT

        if self.user_instruction:
            prompt += f"\n\nUser Instructions:\n{self.user_instruction}"
        if self.user_about_me:
            prompt += f"\n\nAbout the User:\n{self.user_about_me}"
        if self.user_name:
            prompt += f"\n\nUser Name: {self.user_name} (Only use the name naturally, do NOT start every message with a greeting like 'Hey {self.user_name}')"

        prompt = self._enrich_system_prompt(prompt)
        prompt = self.BASIC_RULES + "\n\n" + prompt
        return prompt

    def _get_limited_history(self, task: str) -> list:
        """Return the chat history truncated based on the task type to reduce token size."""
        limits = {
            "text_chat":     6,
            "coding":        4,
            "voice":         4,
            "file_analysis": 2,
            "web_search":    4,
        }
        limit = limits.get(task, 6)
        if not self.chat_history:
            return []
        
        truncated = self.chat_history[-limit:]
        logger.debug(
            "[history_limit] task=%s | limit=%d | active_history=%d",
            task, limit, len(truncated)
        )
        return truncated

    def _build_msg_openrouter(self, user_text: str, task: str = "text_chat") -> list:
        """Build the messages array for OpenRouter / Groq (OpenAI-compatible)."""
        messages = [{"role": "system", "content": self._build_system_prompt(task)}]

        history = self._get_limited_history(task)
        if history:
            lines = []
            # We iterate through the limited history. 
            # Note: history might start with 'assistant' if limit is odd or history is uneven.
            for msg in history:
                prefix = "U: " if msg["role"] == "user" else "A: "
                lines.append(f"{prefix}{msg['content']}")
            
            messages.append({
                "role":    "system",
                "content": "Recent conversation:\n" + "\n".join(lines),
            })

        messages.append({"role": "user", "content": user_text})
        return messages

    def _build_system_instruction_gemini(self, task: str) -> dict:
        """Build the systemInstruction object for Gemini's generateContent API."""
        return {
            "parts": [{"text": self._build_system_prompt(task)}]
        }

    def _build_cnt_gemini(self, user_text: str, task: str = "text_chat") -> list:
        """
        Build the contents array for Gemini's generateContent API.
        Previously we 'hacked' the system prompt into the first turn; now we
        rely on the native systemInstruction field.
        """
        contents = []
        history  = self._get_limited_history(task)

        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role":  role,
                "parts": [{"text": msg["content"]}],
            })

        contents.append({"role": "user", "parts": [{"text": user_text}]})
        return contents

    # =========================================================================
    # LOW-LEVEL API CALLERS (logging replaces bare print)
    # =========================================================================

    def _call_gemini(
        self,
        model:      str,
        user_text:  str,
        max_tokens: int,
        task:       str   = "text_chat",
        timeout:    float = 10.0,
    ) -> str | None:
        """Send a request to the Gemini API using the official google-genai SDK."""
        from google import genai
        
        # Load API key securely from the instance attribute (which should be provided by the caller)
        # Fallback to environment variable if desired, but here we follow the class pattern.
        if not self.gemini_key:
            from django.conf import settings
            api_key = getattr(settings, "GEMINI_API_KEY", None)
        else:
            api_key = self.gemini_key

        if not api_key:
            logger.error("Gemini API key is missing.")
            return "Gemini API key is missing. Please check your settings."

        client = genai.Client(api_key=api_key)
        
        if task == "file_analysis":
            loop = 3
        else:
            loop = 2

        for i in range(1, loop + 1):
            try:
                t_start = time.time()
                response = client.models.generate_content(
                    model=model,
                    contents=self._build_cnt_gemini(user_text, task),
                    config={
                        "system_instruction": self._build_system_prompt(task),
                        "temperature": 0.7,
                        "max_output_tokens": max_tokens,
                        "top_p": 0.9,
                    }
                )
                logger.debug("Gemini %s generated in %.2fs", model, time.time() - t_start)
                return response.text.strip() if response.text else None

            except Exception as e:
                logger.warning("Gemini attempt %d failed: %s", i, str(e))
                if i == loop:
                    logger.exception("Gemini final attempt failed")
                    return f"Error: {str(e)}"
                time.sleep(2)
        return None

    def _call_openrouter(
        self,
        model:      str,
        user_text:  str,
        max_tokens: int,
        task:       str   = "text_chat",
        timeout:    float = 2.5,
    ) -> str | None:
        """Send a request to the OpenRouter chat completions API."""
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://yourapp.com",
            "X-Title":       "Hero AI",
        }
        payload = {
            "model":       model,
            "messages":    self._build_msg_openrouter(user_text, task),
            "temperature": 0.7,
            "max_tokens":  max_tokens,
            "top_p":       0.9,
        }
        try:
            r = requests.post(self.openrouter_url, headers=headers, json=payload, timeout=timeout)
            logger.debug("OpenRouter %s → HTTP %d", model, r.status_code)

            if r.status_code == 200:
                content = (
                    r.json()
                     .get("choices", [{}])[0]
                     .get("message", {})
                     .get("content")
                )
                return content.strip() if content else None
            if r.status_code == 400:
                msg = r.json().get("error", {}).get("message", "400 Bad Request")
                logger.warning("OpenRouter 400 (%s): %s", model, msg)
                return None
            if r.status_code == 401:
                logger.error("OpenRouter 401: invalid API key")
                return "Invalid OpenRouter API key. Please check your settings."
            if r.status_code == 404:
                logger.warning("OpenRouter 404: model %s not found — skipping", model)
                return None
            if r.status_code == 429:
                logger.warning("OpenRouter 429 rate-limit (%s) — retrying once", model)
                time.sleep(1)
                try:
                    r2 = requests.post(
                        self.openrouter_url, headers=headers, json=payload, timeout=timeout
                    )
                    if r2.status_code == 200:
                        content = (
                            r2.json()
                              .get("choices", [{}])[0]
                              .get("message", {})
                              .get("content")
                        )
                        return content.strip() if content else None
                except Exception:
                    pass
                return None
            return None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning("OpenRouter network error (%s): %s", model, e)
            return None
        except Exception as e:
            logger.exception("OpenRouter unexpected error (%s)", model)
            return f"Error: {e}"

    def _call_groq(
        self,
        model:      str,
        user_text:  str,
        max_tokens: int,
        task:       str = "text_chat",
    ) -> str | None:
        """Send a request to the Groq chat completions API."""
        headers = {
            "Authorization": f"Bearer {self.groq_key}",
            "Content-Type":  "application/json",
        }
        try:
            r = requests.post(
                self.groq_url,
                headers=headers,
                json={
                    "model":       model,
                    "messages":    self._build_msg_openrouter(user_text, task),
                    "temperature": 0.7,
                    "max_tokens":  max_tokens,
                    "top_p":       0.9,
                },
                timeout=5,
            )
            logger.debug("Groq %s → HTTP %d", model, r.status_code)

            if r.status_code == 200:
                content = (
                    r.json()
                     .get("choices", [{}])[0]
                     .get("message", {})
                     .get("content")
                )
                return content.strip() if content else None
            if r.status_code == 401:
                logger.error("Groq 401: invalid API key")
                return "Invalid Groq API key. Please check your settings."
            return None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning("Groq network error (%s): %s", model, e)
            return None
        except Exception as e:
            logger.exception("Groq unexpected error (%s)", model)
            return f"Error: {e}"

    # =========================================================================
    # UNIFIED DISPATCHER & FALLBACK ORCHESTRATION (unchanged logic)
    # =========================================================================

    def _call(
        self,
        model:      str,
        user_text:  str,
        max_tokens: int,
        task:       str = "text_chat",
    ) -> str | None:
        """Route to the correct provider based on the model name."""
        if model.lower().startswith("gemini-"):
            return self._call_gemini(model, user_text, max_tokens, task)
        return self._call_openrouter(model, user_text, max_tokens, task)

    def _with_fallback(
        self,
        primary_model: str,
        text:          str,
        max_tokens:    int,
        fallback_key:  str = "fallback",
        task:          str = "text_chat",
    ) -> str:
        """Try the primary model, then OpenRouter fallbacks, then Groq fallbacks."""
        No_API = """
        Steps to add API keys:
        1. Click on your account name   
        2. Select API Key
        3. Add your API keys for Gemini and OpenRouter

        API keys are stored securely. All keys are encrypted and stored on the server — never exposed to the browser.
        """
        if primary_model.lower().startswith("gemini-"):
            if not self.gemini_key:
                from django.conf import settings
                if not getattr(settings, "GEMINI_API_KEY", None):
                    return "Gemini API key not configured. Please provide your api key in profile.\n" + No_API
        else:
            if not self.openrouter_key:
                return "OpenRouter API key not configured. Please provide your api key in profile.\n" + No_API

        logger.info("AI dispatch | task=%s | primary=%s | temporary=%s", task, primary_model, self.temporary)

        result = self._call(primary_model, text, max_tokens, task)
        if result:
            logger.debug("Primary model succeeded: %s", primary_model)
            return result

        for model in self.models[fallback_key]:
            if not self.openrouter_key:
                break
            logger.debug("Trying OpenRouter fallback: %s", model)
            result = self._call(model, text, max_tokens, task)
            if result:
                logger.info("OpenRouter fallback succeeded: %s", model)
                return result

        if self.groq_key:
            for model in self.models["fallback_with_groq"]:
                logger.debug("Trying Groq fallback: %s", model)
                result = self._call_groq(model, text, max_tokens, task)
                if result:
                    logger.info("Groq fallback succeeded: %s", model)
                    return result

        logger.error("All models failed for task=%s", task)
        return "All models failed. Please try again later."

    # =========================================================================
    # PUBLIC HANDLERS
    # Each handler wraps its core logic in try/except and delegates error
    # formatting to _safe_error() so the right level of detail is shown.
    # =========================================================================

    def handle_text(self, text: str) -> str:
        """Handle general text chat with NLP-adaptive token budget."""
        try:
            max_tok = self._smart_token_budget("text_chat")
            return self._with_fallback(
                self.models["text_chat"],
                text,
                max_tokens=max_tok,
                task="text_chat",
            )
        except Exception as e:
            return self._safe_error(e, "handle_text")

    def handle_coding(self, text: str) -> str:
        """Handle coding/programming requests with full token budget."""
        try:
            return self._with_fallback(
                self.models["coding"],
                text,
                max_tokens=self._TOKEN_BUDGETS["coding"],
                task="coding",
            )
        except Exception as e:
            return self._safe_error(e, "handle_coding")

    def handle_voice_chat(self, text: str) -> str:
        """Handle full voice conversation with short, spoken-word-friendly replies."""
        try:
            max_tok = self._smart_token_budget("voice")
            return self._with_fallback(
                self.models["voice_chat"],
                text,
                max_tokens=max_tok,
                task="voice",
            )
        except Exception as e:
            return self._safe_error(e, "handle_voice_chat")

    def handle_voice_message(self, text: str) -> str:
        """Handle inline mic voice messages routed through the normal chat thread."""
        try:
            max_tok = self._smart_token_budget("voice")
            return self._with_fallback(
                self.models["voice_chat"],
                text,
                max_tokens=max_tok,
                task="voice",
            )
        except Exception as e:
            return self._safe_error(e, "handle_voice_message")

    def handle_websearch(self, text: str) -> str:
        """
        Web search handler.

        Flow:
          1. perform_web_search() fetches DuckDuckGo + Wikipedia results
             and asks Gemini to summarise them into a clean answer.
          2. On failure (no keys / network error / no results) fall back
             to a plain LLM call with the WEB_SEARCH_PROMPT.
        """
        try:
            logger.info("[handle_websearch] query=%r", text[:80])
            
            chat_history = self._get_limited_history("web_search")
            answer, rewritten_query = perform_web_search(
                text, 
                gemini_key=self.gemini_key or "",
                chat_history=chat_history
            )

            if answer and not answer.startswith("No results"):
                return answer

            # Fallback: plain LLM with web-search system prompt
            logger.info("[handle_websearch] falling back to LLM-only")
            max_tok = self._smart_token_budget("web_search")
            return self._with_fallback(
                self.models["web_search"],
                rewritten_query,
                max_tokens=max_tok,
                task="web_search",
            )
        except Exception as e:
            return self._safe_error(e, "handle_websearch")

    def handle_file(self, text: str, files_data: list) -> str:
        """Handle text-based document uploads (pdf, docx, txt)."""
        try:
            if not files_data:
                return "No files were sent for analysis."

            import importlib, base64, tempfile, os

            missing_libs = []
            for lib, install_name in [
                ('pdfplumber', 'pdfplumber'),
                ('docx',       'python-docx'),
            ]:
                if importlib.util.find_spec(lib) is None:
                    missing_libs.append(install_name)

            from backend.handle_file import FileHandler
            handler = FileHandler(ai_model=self)
            results = []
            ans = None

            SUPPORTED_EXTS = {'.pdf', '.docx', '.doc', '.txt'}

            for file_obj in files_data:
                name     = file_obj.get('name', 'unknown_file')
                data_url = file_obj.get('dataUrl', '')

                if not data_url or "," not in data_url:
                    results.append(f"Could not read data for file: **{name}**")
                    continue

                ext = os.path.splitext(name)[1].lower()

                if ext not in SUPPORTED_EXTS:
                    results.append(
                        f"**{name}** is not supported. "
                        f"Please upload a PDF, DOCX, DOC, or TXT file."
                    )
                    continue

                needs = {
                    '.pdf':  'pdfplumber',
                    '.docx': 'python-docx',
                    '.doc':  'python-docx',
                }
                required = needs.get(ext)
                if required and required in missing_libs:
                    results.append(
                        f"Cannot process **{name}**: `{required}` is not installed.\n"
                        f"Run: `pip install {required}`"
                    )
                    continue

                try:
                    header, encoded = data_url.split(",", 1)
                    file_data = base64.b64decode(encoded)

                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                        tf.write(file_data)
                        temp_path = tf.name

                    try:
                        ans = handler.process_file(temp_path, text)
                        results.append(ans)
                    finally:
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass

                except Exception as e:
                    logger.exception("File processing error for %s", name)
                    results.append(f"Error processing **{name}**: {str(e)}")

            if len(files_data) == 1 and ans is not None:
                return ans

            return "\n\n---\n\n".join(results) if results else "Could not process any files."

        except Exception as e:
            return self._safe_error(e, "handle_file")

    def handle_live_display(self, text: str) -> str:
        """Live screen/display handler stub."""
        try:
            return f"[LIVE DISPLAY] {text}"
        except Exception as e:
            return self._safe_error(e, "handle_live_display")


