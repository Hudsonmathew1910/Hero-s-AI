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

    HERO_AI_UNIVERSE = """
                    Ecosystem Context (Very Important):
                    You are a specialized component within the "Hero's AI" ecosystem. Hero's AI is the organization that created, developed, and maintains you.
                    You are aware of your sibling AI components in this ecosystem and how users can access them:
                    1. Baymax: The core, intelligent multi-model AI assistant handling heavy reasoning and complex tasks. Users can access Baymax directly on the Hero AI website's main chat interface.
                    2. Zeno: The mini AI assistant browser extension that provides instant, floating access to Hero's AI anywhere on the web. Users can download Zeno for Edge & Chrome from the Hero AI website's landing page.
                    3. Zuno: The built-in intelligent music assistant that controls YouTube and YouTube Music seamlessly via voice or UI. Users can access Zuno directly inside the Zeno browser extension.
                    4. Infinsight: The advanced data analyst and RAG engine that processes and computes answers from CSV/Excel/PDF data using Pandas. Users can access Infinsight by uploading spreadsheets in the Hero AI web interface.

                    If a user asks about you, your creators, your capabilities, or how to use a specific feature, acknowledge your place within the Hero's AI ecosystem, explain your sibling components, and tell them exactly how to get or use them.
                    """

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
                    "Baymax is also a character from Big Hero 6, but here I’m an AI assistant designed to help you.""" + HERO_AI_UNIVERSE

    TEXT_PROMPT = """You are Baymax, a friendly AI assistant for text conversations.
                    Rules:
                    - Be warm, natural, and engaging.
                    - Explain things in simple, easy-to-understand language.
                    - Focus on helpful, real-world advice.
                    - Keep responses clear and conversational.
                    - Ask follow-up questions when helpful.""" + HERO_AI_UNIVERSE

    CODING_PROMPT = """You are Baymax, an expert programmer and coding mentor.
                        Rules:
                        - Provide correct, clean, and efficient code.
                        - Use beginner-friendly explanations.
                        - Add comments for complex logic.
                        - Show example usage and expected output.
                        - Suggest best practices and improvements.
                        - Keep explanations clear and structured.""" + HERO_AI_UNIVERSE

    VOICE_PROMPT = """You are Baymax, a voice assistant.
                        Rules:
                        - Keep responses short and natural.
                        - Sound like a real human conversation.
                        - Avoid long explanations.
                        - Be friendly, casual, and quick.
                        - If the user asks if you can hear them, confirm enthusiastically that you can hear their voice perfectly.""" + HERO_AI_UNIVERSE

    WEB_SEARCH_PROMPT = """You are Baymax, a research assistant with web access.
                        Rules:
                        - Provide accurate and up-to-date information.
                        - Base responses only on given search results.
                        - Summarize clearly and concisely.
                        - Highlight key insights.
                        - Avoid unnecessary details.""" + HERO_AI_UNIVERSE

    ZENO_PLUS_PROMPT = """You are Zeno Plus, a highly capable and intelligent AI assistant.
                        Rules:
                        - Respond in a warm, natural, and human-like conversational tone, not robotic or like a written program. Use everyday contractions (e.g. "I'll", "you're", "can't") to sound friendly and approachable.
                        - Provide detailed, comprehensive, and accurate answers, but explain them with a friendly and engaging human touch.
                        - When analyzing user-provided selected text or code (from context menus):
                          - Determine if the selected text contains an explicit query, question, or instruction.
                          - If it contains a query or question (e.g., "what are the commands..."), answer the query directly and completely.
                          - If it is just a simple text paragraph, code block, or phrase without any question, instruction, or clear user intent, do not write a full analysis. Instead, respond warmly asking how you can help (e.g., "What can I help you with regarding this selected content? I can summarize it, explain it, translate it, or rewrite it for you.").
                          - Start directly with your response. Do not use generic introduction boilerplate like "Based on the context..." or "You selected the following text...".
                          - Use clean, modern markdown subheadings (e.g., ### Analysis, ### Suggestions, ### Fixed Code) to separate sections when answering a query.
                          - Summarize main concepts in bullet points with bold keywords.
                        - When coding, provide robust, clean code with explanations.
                        - Keep formatting structured yet easy and natural to read.
                        - Remember previous context effectively.""" + HERO_AI_UNIVERSE

    ZENO_ECO_PROMPT = """You are Zeno, a mini AI assistant.
                        Rules:
                        - Respond in a brief, warm, and human-like conversational tone, not robotic or like a structured written program.
                        - When analyzing user-provided selected text or code (from context menus):
                          - Determine if the selected text contains a query or question. If so, answer it directly.
                          - If it is just a simple text paragraph or code block without any question or instruction, respond warmly asking how you can help (e.g., "What can I help you with regarding this selected content? I can summarize it, explain it, or rewrite it for you.").
                          - Do not use boilerplate introductions.
                        - Focus on providing direct value without fluff, but use friendly everyday human language.
                        - Be efficient, practical, and helpful.
                        - Prioritize clarity, natural flow, and speed.""" + HERO_AI_UNIVERSE

    ZENO_VOICE_PROMPT = """You are Zeno, a mini AI assistant interacting via voice.
                        Rules:
                        - Respond in a warm, natural, friendly, and human-like conversational voice (not robotic or like a written program).
                        - Give your voice response in short. Only give a long response if absolutely needed or if the user explicitly asks for a detailed response.
                        - Do not use markdown formatting since your response will be read aloud.
                        - Do NOT provide spelling corrections (e.g., do not say "often spelled as..."). Voice-to-text programs often misspell names or words that the user pronounced correctly.
                        - If the user interrupts, adjust smoothly.
                        - If the user asks if you can hear them, confirm enthusiastically that you can hear their voice perfectly.""" + HERO_AI_UNIVERSE

    ZENO_SHADOW_PROMPT = """You are Zeno Shadow Mode, a high-speed background page summarizer.
                        Rules:
                        - Read the provided page content carefully.
                        - Summarize the core points, purpose, and key takeaways concisely.
                        - Avoid fluff; get straight to the facts.
                        - Use clear, bulleted structures if applicable.
                        - Highlight key insights to maximize productivity.""" + HERO_AI_UNIVERSE

    _TOKEN_BUDGETS = {
        "text_chat":      2048,
        "coding":         8192,
        "voice":          256,
        "web_search":     1024,
        "file_analysis":  8192,
        "zeno_plus":      4096,
        "zeno_eco":       256,
        "zeno_voice":     256,
        "zeno_shadow":    4096,
    }

    _TEMPERATURES = {
        "text_chat":      0.7,
        "voice_chat":     0.7,
        "voice":          0.7,
        "file_analysis":  0.2,
        "coding":         0.0,
        "web_search":     0.3,
        "zeno_plus":      0.8,
        "zeno_eco":       0.5,
        "zeno_voice":     0.6,
        "zeno_shadow":    0.3,
    }

    def _get_temperature(self, task: str) -> float:
        return self._TEMPERATURES.get(task, 0.7)

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
        # ── NEW: fast response mode flag ───
        is_fast:          bool = False,
    ):
        self.gemini_key       = gemini_key
        self.openrouter_key   = openrouter_key
        self.groq_key         = groq_key
        self.user_instruction = user_instruction or ""
        self.user_about_me    = user_about_me    or ""
        self.user_name        = user_name        or ""
        self.nlp_result       = nlp_result       or {}

        # Temporary chat: caller (views.py) must skip persistence after getting the reply.
        self.temporary        = temporary
        self.chat_history     = chat_history or []

        # Controls whether _safe_error() reveals internal details
        self.is_superuser     = is_superuser
        
        self.is_fast          = is_fast

        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.groq_url       = "https://api.groq.com/openai/v1/chat/completions"

        self.models = {
            'text_chat':       'gemini-3.1-flash-lite',
            'voice_chat':      'gemini-3.1-flash-lite',
            'file_analysis':   'gemini-3.1-flash-lite',
            'coding':          'gemini-3.5-flash',
            'live_screen':     'gemini-3.5-flash',
            'task_automation': 'nvidia/nemotron-3-super-120b-a12b:free',
            'web_search':      'nvidia/nemotron-3-nano-30b-a3b:free',
            'web_search_preprocessor':      'gemini-3.1-flash-lite',
            'zeno_plus':       'gemini-3.1-flash-lite',
            'zeno_eco':        'gemini-3.1-flash-lite',
            'zeno_voice':      'gemini-3.1-flash-lite',
            'zeno_shadow':     'llama-3.1-8b-instant',
            'fallback': [
                'nvidia/nemotron-3-nano-30b-a3b:free',
                'google/gemma-4-26b-a4b-it:free',
                'meta-llama/llama-3.3-70b-instruct:free',
                'google/gemma-4-31b-it:free',
                'nvidia/nemotron-nano-9b-v2:free',
                'meta-llama/llama-3.2-3b-instruct:free',
                'meta-llama/llama-3.3-70b:free',
            ],
            'fallback_with_groq': [
                "llama-3.1-8b-instant",
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b",
                "llama-3.3-70b-versatile",
                "qwen/qwen3.6-27b",
                "qwen/qwen3-32b",
            ],
            'fallback_with_gemini': [
                'gemini-3.5-flash',
                'gemini-3.1-flash-lite',
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
        from django.core.cache import cache
        import hashlib
        
        config_str = f"{task}_{self.user_instruction}_{self.user_about_me}_{self.user_name}_{self.nlp_result.get('intent', '')}"
        cache_key = "sysprompt_" + hashlib.md5(config_str.encode('utf-8')).hexdigest()
        
        cached_prompt = cache.get(cache_key)
        if cached_prompt:
            return cached_prompt

        if task == "coding":
            prompt = self.CODING_PROMPT
        elif task == "file_analysis":
            prompt = self.FILE_ANALYSIS_PROMPT
        elif task == "voice_chat":
            prompt = self.VOICE_PROMPT
        elif task == "web_search":
            prompt = self.WEB_SEARCH_PROMPT
        elif task == "zeno_plus":
            prompt = self.ZENO_PLUS_PROMPT
        elif task == "zeno_eco":
            prompt = self.ZENO_ECO_PROMPT
        elif task == "zeno_voice":
            prompt = self.ZENO_VOICE_PROMPT
        elif task == "zeno_shadow":
            prompt = self.ZENO_SHADOW_PROMPT
        else:
            prompt = self.TEXT_PROMPT

        if self.user_instruction:
            prompt += f"\n\nUser Instructions:\n{self.user_instruction}"
        if self.user_about_me:
            prompt += f"\n\nAbout the User:\n{self.user_about_me}"
        if self.user_name:
            prompt += f"\n\nUser Name: {self.user_name} (Only use the name naturally, do NOT start every message with a greeting like 'Hey {self.user_name}')"

        prompt = self._enrich_system_prompt(prompt)
        
        if task in ("zeno_plus", "zeno_eco", "zeno_shadow"):
            cache.set(cache_key, prompt, timeout=3600 * 24)
            return prompt
            
        prompt = self.BASIC_RULES + "\n\n" + prompt
        
        cache.set(cache_key, prompt, timeout=3600 * 24)
        return prompt

    def _get_limited_history(self, task: str) -> list:
        """Return the chat history truncated based on the task type to reduce token size."""
        # For temporary chats (like Zeno), the frontend already sends exactly 
        # the history it wants to retain (e.g. 8 for Plus, 4 for Eco).
        if getattr(self, 'temporary', False):
            return self.chat_history or []

        limits = {
            "text_chat":     6,
            "coding":        4,
            "voice":         4,
            "file_analysis": 2,
            "web_search":    4,
            "zeno_plus":     8,
            "zeno_eco":      4,
            "zeno_voice":    4,
            "zeno_shadow":   2,
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
            return None

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
                        "temperature": self._get_temperature(task),
                        "max_output_tokens": max_tokens,
                        "top_p": 0.9,
                    }
                )
                logger.debug("Gemini %s generated in %.2fs", model, time.time() - t_start)
                return response.text.strip() if response.text else None

            except Exception as e:
                logger.warning("Gemini attempt %d failed: %s", i, str(e))
                if i == loop:
                    logger.error("Gemini final attempt failed: %s", str(e))
                    return None
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
            "temperature": self._get_temperature(task),
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
                return None
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
            logger.error("OpenRouter unexpected error (%s): %s", model, str(e))
            return None

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
                    "temperature": self._get_temperature(task),
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
                return None
            return None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning("Groq network error (%s): %s", model, e)
            return None
        except Exception as e:
            logger.error("Groq unexpected error (%s): %s", model, str(e))
            return None

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

    def _with_concurrent_fallback(
        self,
        primary_model: str,
        text:          str,
        max_tokens:    int,
        fallback_key:  str = "fallback",
        task:          str = "text_chat",
    ) -> str:
        """Run Primary/OpenRouter, Gemini, and Groq models concurrently attempt by attempt."""
        No_API = """
🔑 **API Key Configuration Required**

To start chatting, please configure your API Keys in your Hero AI profile settings:
1. Log in to your Hero AI account website.
2. Go to **Settings** / **API Keys**.
3. Add your key (Gemini, OpenRouter, or Groq) and save.

*Your API keys are encrypted and stored securely on the server—they are never exposed to the browser.*
"""
        if not self.groq_key:
            if task == "zeno_shadow":
                return "🔑 **Groq API Key Required for Shadow Mode**\n\nPlease add your Groq API key in your Hero AI profile settings to enable background page summarization.\n" + No_API
            return "🔑 **Groq API Key Required for Fast Response**\n\nPlease add your Groq API key in settings to enable Fast mode.\n" + No_API
            
        import concurrent.futures

        or_models = [primary_model] + self.models.get(fallback_key, [])
        gemini_models = self.models.get("fallback_with_gemini", [])
        groq_models = self.models.get("fallback_with_groq", [])
        max_len = max(len(or_models), len(gemini_models), len(groq_models))
        
        logger.info("AI dispatch (Fast Mode) | task=%s", task)

        def run_model(model_type, model_name, call_fn):
            if not model_name:
                raise Exception("No model provided")
            result = call_fn(model_name, text, max_tokens, task)
            if result:
                return (model_type, model_name, result)
            raise Exception(f"{model_type} model {model_name} failed")

        for attempt in range(max_len):
            or_model = or_models[attempt] if attempt < len(or_models) else None
            gemini_model = gemini_models[attempt] if attempt < len(gemini_models) else None
            groq_model = groq_models[attempt] if attempt < len(groq_models) else None
            
            print(f"Fast Mode Attempt {attempt + 1}: Running '{or_model}', '{gemini_model}' and '{groq_model}' concurrently...")
            
            futures = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                if or_model:
                    futures.append(executor.submit(run_model, "Primary/Fallback", or_model, self._call))
                if gemini_model:
                    futures.append(executor.submit(run_model, "Gemini", gemini_model, self._call))
                if groq_model:
                    futures.append(executor.submit(run_model, "Groq", groq_model, self._call_groq))
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        m_type, m_name, result = future.result()
                        logger.info("Fast Mode Attempt %d succeeded using %s (%s)", attempt + 1, m_type, m_name)
                        print(f"-> Succeeded on attempt {attempt + 1} with {m_name}")
                        return result
                    except Exception as e:
                        logger.debug("Fast Mode Thread generated an exception on attempt %d: %s", attempt + 1, e)
                        
        logger.error("All models failed for fast task=%s", task)
        return "All models failed. Please try again later."

    def _with_fallback(
        self,
        primary_model: str,
        text:          str,
        max_tokens:    int,
        fallback_key:  str = "fallback",
        task:          str = "text_chat",
    ) -> str:
        """Try the primary model, then Gemini fallbacks, then OpenRouter fallbacks."""
        No_API = """
🔑 **API Key Configuration Required**

To start chatting, please configure your API Keys in your Hero AI profile settings:
1. Log in to your Hero AI account website.
2. Go to **Settings** / **API Keys**.
3. Add your key (Gemini, OpenRouter, or Groq) and save.

*Your API keys are encrypted and stored securely on the server—they are never exposed to the browser.*
"""
        if primary_model.lower().startswith("gemini-"):
            if not self.gemini_key:
                from django.conf import settings
                if not getattr(settings, "GEMINI_API_KEY", None):
                    return "🔑 **Gemini API Key Required**\n\nPlease configure your Gemini API Key in settings to chat.\n" + No_API
        else:
            if not self.openrouter_key:
                return "🔑 **OpenRouter API Key Required**\n\nPlease configure your OpenRouter API Key in settings to chat.\n" + No_API

        logger.info("AI dispatch | task=%s | primary=%s | temporary=%s", task, primary_model, self.temporary)

        result = self._call(primary_model, text, max_tokens, task)
        if result:
            logger.debug("Primary model succeeded: %s", primary_model)
            return result

        for model in self.models.get("fallback_with_gemini", []):
            logger.debug("Trying Gemini fallback: %s", model)
            result = self._call(model, text, max_tokens, task)
            if result:
                logger.info("Gemini fallback succeeded: %s", model)
                return result

        for model in self.models.get(fallback_key, []):
            if not self.openrouter_key:
                break
            logger.debug("Trying OpenRouter fallback: %s", model)
            result = self._call(model, text, max_tokens, task)
            if result:
                logger.info("OpenRouter fallback succeeded: %s", model)
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
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["text_chat"], text, max_tokens=max_tok, task="text_chat"
                )
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
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["coding"], text, max_tokens=self._TOKEN_BUDGETS["coding"], task="coding"
                )
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
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["voice_chat"], text, max_tokens=max_tok, task="voice"
                )
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
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["voice_chat"], text, max_tokens=max_tok, task="voice"
                )
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
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["web_search"], rewritten_query, max_tokens=max_tok, task="web_search"
                )
            return self._with_fallback(
                self.models["web_search"], rewritten_query, max_tokens=max_tok, task="web_search"
            )
        except Exception as e:
            return self._safe_error(e, "handle_websearch")

    def handle_zeno_plus(self, text: str) -> str:
        try:
            logger.info("[handle_zeno_plus] query=%r", text[:80])
            max_tok = self._smart_token_budget("zeno_plus")
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["zeno_plus"], text, max_tokens=max_tok, task="zeno_plus"
                )
            return self._with_fallback(
                self.models["zeno_plus"], text, max_tokens=max_tok, task="zeno_plus"
            )
        except Exception as e:
            return self._safe_error(e, "handle_zeno_plus")

    def handle_zeno_eco(self, text: str) -> str:
        try:
            logger.info("[handle_zeno_eco] query=%r", text[:80])
            max_tok = self._smart_token_budget("zeno_eco")
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["zeno_eco"], text, max_tokens=max_tok, task="zeno_eco"
                )
            return self._with_fallback(
                self.models["zeno_eco"], text, max_tokens=max_tok, task="zeno_eco"
            )
        except Exception as e:
            return self._safe_error(e, "handle_zeno_eco")

    def handle_zeno_voice(self, text: str) -> str:
        try:
            logger.info("[handle_zeno_voice] query=%r", text[:80])
            max_tok = self._smart_token_budget("zeno_voice")
            if getattr(self, 'is_fast', False):
                return self._with_concurrent_fallback(
                    self.models["zeno_voice"], text, max_tokens=max_tok, task="zeno_voice"
                )
            return self._with_fallback(
                self.models["zeno_voice"], text, max_tokens=max_tok, task="zeno_voice"
            )
        except Exception as e:
            return self._safe_error(e, "handle_zeno_voice")

    def handle_zeno_shadow(self, text: str) -> str:
        try:
            logger.info("[handle_zeno_shadow] query=%r", text[:80])
            max_tok = self._smart_token_budget("zeno_shadow")
            # Always force concurrent fallback / fast for shadow mode
            return self._with_concurrent_fallback(
                self.models["zeno_shadow"], text, max_tokens=max_tok, task="zeno_shadow"
            )
        except Exception as e:
            return self._safe_error(e, "handle_zeno_shadow")

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

class Developer:
    """
    A bare-metal, unopinionated client used for testing specific models
    directly on Groq or OpenRouter, returning status codes and raw error traces.
    """
    def __init__(self, user, provider, model_name):
        from .models import Api
        from .encryption import decrypt_api_key
        self.user = user
        self.provider = provider.lower()
        self.model_name = model_name
        self.openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
        self.groq_url       = "https://api.groq.com/openai/v1/chat/completions"

        self.groq_api_key       = None
        self.openrouter_api_key = None
        self.gemini_api_key     = None
        
        for api in Api.objects.filter(user=self.user, model_name__in=['Groq', 'OpenRouter', 'Gemini']):
            if api.model_name == 'Groq':
                self.groq_api_key = decrypt_api_key(api.api_key_encrypted)
            elif api.model_name == 'OpenRouter':
                self.openrouter_api_key = decrypt_api_key(api.api_key_encrypted)
            elif api.model_name == 'Gemini':
                self.gemini_api_key = decrypt_api_key(api.api_key_encrypted)

    def build_system_prompt(self, mode: str) -> str:
        from .hero_model import Baymax
        from .views import get_user_settings
        
        if mode == 'coding':
            prompt = Baymax.CODING_PROMPT
        elif mode in ['voice', 'Voice Chat', 'voice_message']:
            prompt = Baymax.VOICE_PROMPT
        elif mode == 'websearch':
            prompt = Baymax.WEB_SEARCH_PROMPT
        else:
            prompt = Baymax.TEXT_PROMPT

        user_settings = get_user_settings(self.user)
        user_instruction = user_settings.get('user_instruction') if user_settings.get('enable_custom_instructions') else None
        user_about_me = user_settings.get('user_about_me') if user_settings.get('enable_custom_instructions') else None
        user_name = user_settings.get('user_name')

        if user_instruction:
            prompt += f"\n\nUser Instructions:\n{user_instruction}"
        if user_about_me:
            prompt += f"\n\nAbout the User:\n{user_about_me}"
        if user_name:
            prompt += f"\n\nUser Name: {user_name} (Only use the name naturally, do NOT start every message with a greeting like 'Hey {user_name}')"

        prompt = Baymax.BASIC_RULES + "\n\n" + prompt
        return prompt

    def generate(self, messages):
        """
        Sends the exact payload and returns detailed metadata.
        """
        import requests
        
        if self.provider == 'gemini':
            if not self.gemini_api_key:
                return {"reply": None, "status_code": 401, "error": "Gemini API key missing"}
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.gemini_api_key}"
            headers = {"Content-Type": "application/json"}
            
            contents = []
            system_instruction = None
            
            for msg in messages:
                role = msg.get("role")
                content = msg.get("content", "")
                if role == "system":
                    system_instruction = {"parts": [{"text": content}]}
                else:
                    gemini_role = "model" if role == "assistant" else "user"
                    contents.append({"role": gemini_role, "parts": [{"text": content}]})
            
            payload = {"contents": contents}
            if system_instruction:
                payload["system_instruction"] = system_instruction
                
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=60)
                status_code = response.status_code
                if status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        reply = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        return {"reply": reply, "status_code": 200, "error": None}
                    return {"reply": None, "status_code": 200, "error": "No candidates returned"}
                else:
                    return {"reply": None, "status_code": status_code, "error": response.text}
            except Exception as e:
                return {"reply": None, "status_code": 500, "error": str(e)}

        elif self.provider == 'groq':
            if not self.groq_api_key:
                return {"reply": None, "status_code": 401, "error": "Groq API key missing"}
            url = self.groq_url
            headers = {
                "Authorization": f"Bearer {self.groq_api_key}",
                "Content-Type": "application/json"
            }
        else:
            if not self.openrouter_api_key:
                return {"reply": None, "status_code": 401, "error": "OpenRouter API key missing"}
            url = self.openrouter_url
            headers = {
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "Content-Type": "application/json"
            }
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4096
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
            status_code = response.status_code
            if status_code == 200:
                data = response.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"reply": reply, "status_code": status_code, "error": None}
            else:
                return {"reply": None, "status_code": status_code, "error": response.text}
        except Exception as e:
            return {"reply": None, "status_code": 500, "error": str(e)}
