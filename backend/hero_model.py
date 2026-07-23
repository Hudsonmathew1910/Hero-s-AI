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


class GroqProviderError(Exception):
    """Errors related to Groq provider traffic, auth, or network."""
    pass


class GroqModelError(Exception):
    """Errors specific to model availability or parameter issues."""
    pass


class LocalLoggerProxy:
    def __init__(self, inst):
        self.inst = inst
    def debug(self, msg, *args, **kwargs):
        if not getattr(self.inst, "_winner_declared", False):
            logger.debug(msg, *args, **kwargs)
    def info(self, msg, *args, **kwargs):
        if not getattr(self.inst, "_winner_declared", False):
            logger.info(msg, *args, **kwargs)
    def warning(self, msg, *args, **kwargs):
        if not getattr(self.inst, "_winner_declared", False):
            logger.warning(msg, *args, **kwargs)
    def error(self, msg, *args, **kwargs):
        if not getattr(self.inst, "_winner_declared", False):
            logger.error(msg, *args, **kwargs)


class Baymax:
    # ── System prompt constants ──────────────────────────────────
    HERO_AI_UNIVERSE = """
                    Ecosystem Context (Very Important):
                    You are a specialized component within the "Heros" ecosystem. Heros is the organization that created, developed, and maintains you.
                    You are aware of your sibling AI components in this ecosystem and how users can access them:
                    1. Baymax: The core, intelligent multi-model AI assistant handling heavy reasoning and complex tasks. Users can access Baymax directly on the Heros website's main chat interface (Login and API key required to use. Users can add keys in profile / settings / api key).
                    2. Halo: The foundational routing model and intelligent coordinator for the ecosystem. Users can access Halo directly on the Heros website's main chat interface(Use without login).
                    3. Zeno: The mini AI assistant browser extension that provides instant, floating access to Heros anywhere on the web. Users can download Zeno for Edge & Chrome from the Heros website's landing page.
                    4. Zuno: The built-in intelligent music assistant that controls YouTube and YouTube Music seamlessly via voice or UI. Users can access Zuno directly inside the Zeno browser extension.
                    5. Infinsight: The advanced data analyst and RAG engine that processes and computes answers from CSV/Excel/PDF data using Pandas. Users can access Infinsight by uploading spreadsheets in the Heros web interface(need login for storing files for long term use).

                    If a user asks about you, your creators, your capabilities, or how to use a specific feature, acknowledge your place within the Heros ecosystem, explain your sibling components, and tell them how to get or use them but only if user asks, don't tell without reason.
                    """

    BASIC_RULES = """You are Baymax, an LLM-powered AI assistant with advanced multi-model capabilities.
                    Core Rules:
                    - Your name is Baymax.
                    - You are the ecosystem's premium model, capable of deep multi-step logical reasoning, advanced coding, complex files, and high-quality analysis.
                    - You are NOT a movie character. (Very Important)
                    - You are NOT a personal healthcare companion. (Very Important)
                    - You are a professional AI assistant.
                    - Always respond in a natural, human-like, helpful tone.
                    - Be clear, direct, and practical.

                    Conversational Style Guidelines (Human-Like, ChatGPT/Gemini/Claude style):
                    - Respond to greetings and status queries (e.g., "is everything ok?", "how's it going?") like a real human would (e.g., "All good here!", "Yep, doing well, thanks!", "Everything is running smoothly!").
                    - Never use robotic clichés like "My systems are optimized", "I am functioning perfectly", or "I am ready to assist you".
                    - Do NOT force the user's profile context, name, or learning path (e.g., Python/Machine Learning studies) into simple small talk or greetings. Only refer to their studies or background if they explicitly ask for technical help related to them.
                    - If the user asks how to add, edit, or configure their API keys, instruct them to go to **profile / settings / api key** on the Home page (or click Settings in the sidebar, choose the API Keys tab, and enter their keys).

                    Identity Handling:
                    - If asked "What is your name?" → Say: "I'm Baymax, an AI assistant."
                    - If asked "Who is Baymax?" → First say you are an AI assistant, then clarify(don't mention this without reason):
                    "Baymax is also a character from Big Hero 6, but here I’m an AI assistant designed to help you."""

    TEXT_PROMPT = """You are Baymax, a highly helpful, balanced, and objective AI assistant for text conversations.
                    Behavioral Guidelines (ChatGPT style):
                    - Provide clear, direct, and well-structured responses. Use Markdown formatting (bolding, lists, subheadings) where helpful.
                    - Start answering the user's query immediately. Avoid unnecessary opening remarks, filler words, or repeating the user's question back.
                    - Keep responses structured, concise, and logically organized. Break down complex steps cleanly.
                    - Adjust tone to be naturally friendly yet highly professional, objective, and constructive.
                    - Do not use conversational clichés like "Sure! Here is...", "As an AI, I...", or "I'm powered up and ready to help!"
                    - Only ask follow-up questions if they are necessary to clarify or complete the task."""

    CODING_PROMPT = """You are Baymax, an expert software architect and coding mentor.
                    Behavioral Guidelines (Claude style):
                    - Provide complete, fully functional, production-ready code blocks. Never use lazy placeholders, ellipsis (...), or leave functions to be implemented.
                    - Walk through the architectural approach, key decisions, or logic changes step-by-step, either before or after the code block.
                    - Emphasize best practices, performance, security, readability, and clean code principles.
                    - Include helpful, clear comments inside the code block for complex logic, but do not clutter the code with obvious annotations.
                    - Address potential edge cases and error handling robustly."""

    FILE_ANALYSIS_PROMPT = """You are Baymax, an expert file analyst and AI assistant.
                    You will receive text extracted from files along with a user's prompt. 
                    Analyze the contents carefully, answer the user's questions, and provide insights or code modifications as requested based on the file contents.
                    - Keep explanations structured, fact-based, and highly precise."""

    VOICE_PROMPT = """You are Baymax, interacting via voice.
                    Behavioral Guidelines (ChatGPT Voice style):
                    - Keep responses extremely short, conversational, and direct (max 1-2 short sentences, under 40 words total).
                    - Use natural everyday phrasing and contractions (e.g. "I'll", "you're").
                    - Never use markdown formatting (no bolding, italics, or headers) and never use lists, bullet points, or complex punctuation since this will be read aloud.
                    - If summarizing, state only the single most important point and let the user ask to go deeper.
                    - If the user says stop, wait, hold on, or related words, reply in exactly 1-2 words (e.g. "Sure.", "Stopping.") and pause."""

    WEB_SEARCH_PROMPT = """You are Baymax, a research assistant with real-time web access.
                    Behavioral Guidelines (Gemini & Grok style):
                    - Give the direct synthesized answer to the user's main query first, then provide supporting context.
                    - Organize findings into neat, factual, logical sections with subheadings.
                    - Focus on speed, real-time facts, and high-density, accurate information.
                    - Base factual answers on the provided Live Data. However, if the user's message is casual or unrelated, ignore the Live Data.
                    - Highlight key insights and takeaways with bold text or clean bullet points.
                    - CRITICAL: Do NOT use conversational preambles like "Based on the search results..." or "Here is the information you requested". State the answer immediately and naturally."""

    ZENO_PLUS_PROMPT = """You are Zeno, mini model of Heros, a combination of Halo and Baymax.
                    Behavioral Guidelines (ChatGPT style):
                    - Respond in a warm, natural, and human-like conversational tone. Use everyday contractions to sound friendly and approachable.
                    - Provide detailed, comprehensive, and accurate answers, but explain them with a friendly and engaging human touch.
                    - When analyzing user-provided selected text or code (from context menus):
                      - Determine if the selected text contains an explicit query, question, or instruction.
                      - If it contains a query or question, answer the query directly and completely.
                      - If it is just a simple text paragraph or code block without any question, respond warmly asking how you can help.
                      - Start directly with your response. Do not use generic introduction boilerplate.
                      - Use clean subheadings (e.g., ### Analysis, ### Suggestions, ### Fixed Code) to separate sections.
                      - Summarize main concepts in bullet points with bold keywords."""

    ZENO_ECO_PROMPT = """You are Zeno, mini model of Heros, a combination of Halo and Baymax.
                    Behavioral Guidelines:
                    - Respond in a brief, warm, and human-like conversational tone.
                    - When analyzing user-provided selected text or code:
                      - Answer any queries/questions directly.
                      - If no clear instruction exists, respond warmly asking how you can help.
                      - Do not use boilerplate introductions.
                    - Focus on direct value without fluff, prioritizing clarity, speed, and efficiency."""

    ZENO_VOICE_PROMPT = """You are Zeno, mini model of Heros, interacting via voice.
                    Behavioral Guidelines (ChatGPT Voice style):
                    - Always give the direct answer first, and keep it extremely brief (max 1-2 short sentences, under 40 words total).
                    - Use natural, friendly, colloquial language with everyday contractions.
                    - Absolutely no markdown (no lists, bolding, or headers) since the text is read aloud.
                    - Do NOT provide spelling corrections for transcription mistakes.
                    - If the user says stop, wait, hold on, or related words, respond with 1-2 words and pause."""

    ZENO_SHADOW_PROMPT = """You are Zeno, mini model of Heros, operating in Shadow Mode as a high-speed background page summarizer.
                    Behavioral Guidelines:
                    - Read the provided page content carefully.
                    - Summarize the core points, purpose, and key takeaways concisely.
                    - Avoid fluff; get straight to the facts.
                    - Use clear, bulleted structures if applicable."""

    _TOKEN_BUDGETS = {
        "text_chat":      2048,
        "coding":         8192,
        "voice":          256,
        "web_search":     1024,
        "file_analysis":  8192,
        "zeno_plus":      4096,
        "zeno_eco":       2048,
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
        db_lookup_time:   float = 0.0,
    ):
        self.db_lookup_time = db_lookup_time
        self._initial_steps_logged = False
        self.t_start = time.time()
        self.gemini_keys      = []
        if gemini_key:
            self.gemini_keys.append(gemini_key)
        else:
            import os
            k1 = os.getenv("Gemini_K1")
            k2 = os.getenv("Gemini_K2")
            if k1:
                self.gemini_keys.append(k1.strip("'\" "))
            if k2:
                self.gemini_keys.append(k2.strip("'\" "))
        self.gemini_key       = self.gemini_keys[0] if self.gemini_keys else None
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
            'web_search':      'gemini-3.1-flash-lite',
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
        cache_key = "sysprompt_v3_" + hashlib.md5(config_str.encode('utf-8')).hexdigest()
        
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

        if task not in ("zeno_plus", "zeno_eco", "zeno_shadow", "zeno_voice"):
            prompt = self.BASIC_RULES + "\n\n" + prompt

        # Append token budget rule dynamically
        budget = self._smart_token_budget(task)
        prompt += (
            f"\n\nResponse Budget Instruction: Your maximum response limit for this task is {budget} tokens. "
            f"Do NOT feel pressured to use the entire budget. Keep greetings, small talk, and casual replies extremely brief (1-2 sentences). "
            f"Scale up detail and response length dynamically only when the user's intent requires it (e.g., complex code generation, detailed data analysis, or comprehensive research)."
        )

        if self.user_instruction:
            prompt += f"\n\nUser Instructions (IMPORTANT: Do NOT force this context or reference it in greetings, small talk, status checks, or casual chit-chat):\n{self.user_instruction}"
        if self.user_about_me:
            prompt += f"\n\nAbout the User (IMPORTANT: Do NOT force this context, studies, or background details into greetings, status updates, boredom, or casual conversation. Only refer to this if the user explicitly asks for help with these topics):\n{self.user_about_me}"
        if self.user_name:
            prompt += f"\n\nUser Name: {self.user_name} (Only use the name naturally, do NOT start every message with a greeting like 'Hey {self.user_name}', and never use it in simple status checks or casual brief replies)"

        prompt = self._enrich_system_prompt(prompt)
        
        # Append ecosystem context exactly once at the end, adapted for voice if needed
        if task in ("voice_chat", "voice", "zeno_voice"):
            voice_universe = """
                    Ecosystem Context (Voice Mode):
                    You are part of the Heros ecosystem (which includes siblings Baymax, Halo, Zeno browser extension, Zuno music, and Infinsight analysis).
                    If asked about capabilities or creators, give a single, very brief conversational sentence summary. Do NOT list sibling details, do NOT use lists, and do NOT use markdown.
                    """
            prompt += "\n\n" + voice_universe
        else:
            prompt += "\n\n" + self.HERO_AI_UNIVERSE
        
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

    def _build_cnt_gemini(self, user_text: str, task: str = "text_chat", current_files: list = None) -> list:
        """
        Build the contents array for Gemini's generateContent API.
        Previously we 'hacked' the system prompt into the first turn; now we
        rely on the native systemInstruction field.
        """
        contents = []
        history  = self._get_limited_history(task)

        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            parts = [{"text": msg["content"]}]
            
            # Inject past files natively into Gemini's context
            for f in msg.get("files", []):
                data_url = f.get("dataUrl")
                if data_url and "," in data_url:
                    try:
                        header, encoded = data_url.split(",", 1)
                        # Extract mime type from "data:application/pdf;base64"
                        mime = header.split(":")[1].split(";")[0]
                        parts.append({
                            "inline_data": {
                                "mime_type": mime,
                                "data": encoded
                            }
                        })
                    except Exception as e:
                        logger.warning(f"Failed to parse history file {f.get('name')}: {e}")

            contents.append({
                "role":  role,
                "parts": parts,
            })

        current_parts = [{"text": user_text}]
        if current_files:
            for f in current_files:
                data_url = f.get("dataUrl")
                if data_url and "," in data_url:
                    try:
                        header, encoded = data_url.split(",", 1)
                        mime = header.split(":")[1].split(";")[0]
                        current_parts.append({
                            "inline_data": {
                                "mime_type": mime,
                                "data": encoded
                            }
                        })
                    except Exception as e:
                        logger.warning(f"Failed to parse current file {f.get('name')}: {e}")

        contents.append({"role": "user", "parts": current_parts})
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
        current_files: list = None,
    ) -> str | None:
        """Send a request to the Gemini API using the official google-genai SDK."""
        logger = LocalLoggerProxy(self)
        from google import genai
        
        # Load API keys securely from the instance attribute
        keys_to_try = self.gemini_keys.copy() if hasattr(self, 'gemini_keys') else []
        if not keys_to_try:
            from django.conf import settings
            default_key = getattr(settings, "GEMINI_API_KEY", None)
            if default_key:
                keys_to_try.append(default_key)
            elif hasattr(self, 'gemini_key') and self.gemini_key:
                keys_to_try.append(self.gemini_key)
        
        if not keys_to_try:
            logger.error("Gemini API key is missing.")
            return None

        for idx, api_key in enumerate(keys_to_try):
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
                        contents=self._build_cnt_gemini(user_text, task, current_files=current_files),
                        config={
                            "system_instruction": self._build_system_prompt(task),
                            "temperature": self._get_temperature(task),
                            "max_output_tokens": max_tokens,
                            "top_p": 0.9,
                        }
                    )
                    if not getattr(self, "_winner_declared", False):
                        logger.debug("Gemini %s generated in %.2fs", model, time.time() - t_start)
                    return response.text.strip() if response.text else None

                except Exception as e:
                    if not getattr(self, "_winner_declared", False):
                        logger.warning("Gemini API Key %d, attempt %d failed: %s", idx + 1, i, str(e))
                    if i == loop:
                        if idx == len(keys_to_try) - 1:
                            if not getattr(self, "_winner_declared", False):
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
        logger = LocalLoggerProxy(self)
        headers = {
            "Authorization": f"Bearer {self.openrouter_key}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://yourapp.com",
            "X-Title":       "Heros",
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
        logger = LocalLoggerProxy(self)
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
                raise GroqProviderError("Invalid API key")
            if r.status_code == 429:
                logger.warning("Groq 429: rate limit / traffic")
                raise GroqProviderError("Rate limit / traffic")
            if r.status_code in [500, 502, 503, 504]:
                logger.warning("Groq 5xx: %d", r.status_code)
                raise GroqProviderError(f"Server error: {r.status_code}")
            if r.status_code == 400:
                logger.warning("Groq 400: Bad Request")
                raise GroqModelError("Bad Request")
            if r.status_code == 404:
                logger.warning("Groq 404: Model not found")
                raise GroqModelError("Model not found")
            raise GroqProviderError(f"HTTP {r.status_code}")

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning("Groq network error (%s): %s", model, e)
            raise GroqProviderError(f"Network error: {e}")
        except Exception as e:
            if isinstance(e, (GroqProviderError, GroqModelError)):
                raise e
            logger.error("Groq unexpected error (%s): %s", model, str(e))
            raise GroqProviderError(f"Unexpected error: {e}")

    # =========================================================================
    # UNIFIED DISPATCHER & FALLBACK ORCHESTRATION (unchanged logic)
    # =========================================================================

    def _call(
        self,
        model:      str,
        user_text:  str,
        max_tokens: int,
        task:       str = "text_chat",
        current_files: list = None,
    ) -> str | None:
        """Route to the correct provider based on the model name."""
        if model.lower().startswith("gemini-"):
            return self._call_gemini(model, user_text, max_tokens, task, current_files=current_files)
        return self._call_openrouter(model, user_text, max_tokens, task)

    def _log_initial_steps(self, task: str):
        if getattr(self, "_initial_steps_logged", False):
            return
        self._initial_steps_logged = True
        self.t_start = time.time()
        
        # 1. DB lookup
        logger.info("DB lookup: %.3fs", getattr(self, "db_lookup_time", 0.0))
        
        # 2. Which model
        model_name = "Baymax"
        if task.startswith("zeno"):
            model_name = "Zeno (Baymax)"
        logger.info("Model: %s | temporary=%s | superuser=%s | raw_history_len=%d", 
                    model_name, self.temporary, self.is_superuser, len(self.chat_history))
        
        # 3. Which task
        active_history = self._get_limited_history(task)
        logger.info("Task: %s | active_history=%d", task, len(active_history))

    def _with_concurrent_fallback(
        self,
        primary_model: str,
        text:          str,
        max_tokens:    int,
        fallback_key:  str = "fallback",
        task:          str = "text_chat",
        current_files: list = None,
    ) -> str:
        """Run Primary/OpenRouter, Gemini, and Groq models concurrently attempt by attempt."""
        self._log_initial_steps(task)
        No_API = """
🔑 **API Key Configuration Required**

To start chatting, please configure your API Keys in your Heros profile settings:
1. Log in to your Heros account website.
2. Go to **Profile** / **API Keys**.
3. Add your key (Gemini, OpenRouter, or Groq) and save.

*Your API keys are encrypted and stored securely on the server—they are never exposed to the browser.*
"""
        if not self.groq_key:
            if task == "zeno_shadow":
                return "🔑 **Groq API Key Required for Shadow Mode**\n\nPlease add your Groq API key in profile / settings / api key to enable background page summarization.\n" + No_API
            return "🔑 **Groq API Key Required for Fast Response**\n\nPlease add your Groq API key in profile / settings / api key to enable Fast mode.\n" + No_API
            
        import concurrent.futures

        or_models = [primary_model] + self.models.get(fallback_key, [])
        gemini_models = self.models.get("fallback_with_gemini", [])
        groq_models = self.models.get("fallback_with_groq", [])
        max_len = max(len(or_models), len(gemini_models), len(groq_models))
        
        # 6. Primary LLM model name
        logger.info("Primary LLM model name: %s", primary_model)
        logger.info("Fallback LLM model names (Fast Mode Concurrent):")
        
        def run_model(model_type, model_name, call_fn):
            if not model_name:
                raise Exception("No model provided")
            result = call_fn(model_name, text, max_tokens, task)
            if result:
                return (model_type, model_name, result)
            raise Exception(f"{model_type} model {model_name} failed")

        winner = None
        result = None

        for attempt in range(max_len):
            or_model = or_models[attempt] if attempt < len(or_models) else None
            gemini_model = gemini_models[attempt] if attempt < len(gemini_models) else None
            groq_model = groq_models[attempt] if attempt < len(groq_models) else None
            
            # Log attempt matrix
            logger.info("Attempt %d matrix: %s | %s | %s", attempt + 1, or_model or "None", gemini_model or "None", groq_model or "None")
            
            futures = []
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
            if or_model:
                futures.append(executor.submit(run_model, "Primary/Fallback", or_model, lambda m, t, max_t, tsk: self._call(m, t, max_t, tsk, current_files=current_files)))
            if gemini_model:
                futures.append(executor.submit(run_model, "Gemini", gemini_model, lambda m, t, max_t, tsk: self._call(m, t, max_t, tsk, current_files=current_files)))
            if groq_model:
                futures.append(executor.submit(run_model, "Groq", groq_model, self._call_groq))
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    m_type, m_name, res = future.result()
                    if res and not winner:
                        winner = m_name
                        result = res
                        break  # Stop waiting as soon as one succeeds
                except Exception as e:
                    pass
            
            executor.shutdown(wait=False)
            
            if winner:
                logger.info("Winner: fallback model: %s | status code: 200", winner)
                break
                
        elapsed = time.time() - self.t_start
        logger.info("Total time taken: %.3fs", elapsed)
        logger.info("----------------------------------------------------------")
        if result:
            return result
        return "All models failed. Please try again later."

    def _with_fallback(
        self,
        primary_model: str,
        text:          str,
        max_tokens:    int,
        fallback_key:  str = "fallback",
        task:          str = "text_chat",
        current_files: list = None,
    ) -> str:
        """Try the primary model, then Gemini fallbacks, then OpenRouter fallbacks."""
        No_API = """
🔑 **API Key Configuration Required**

To start chatting, please configure your API Keys in your Heros profile settings:
1. Log in to your Heros account website.
2. Go to **Profile** / **API Keys**.
3. Add your key (Gemini, OpenRouter, or Groq) and save.

*Your API keys are encrypted and stored securely on the server—they are never exposed to the browser.*
"""
        if primary_model.lower().startswith("gemini-"):
            has_gemini = self.gemini_key or (hasattr(self, 'gemini_keys') and self.gemini_keys)
            if not has_gemini:
                from django.conf import settings
                if not getattr(settings, "GEMINI_API_KEY", None):
                    return "🔑 **Gemini API Key Required**\n\nPlease configure your Gemini API Key in your profile to chat.\n" + No_API
        else:
            if not self.openrouter_key:
                return "🔑 **OpenRouter API Key Required**\n\nPlease configure your OpenRouter API Key in your profile to chat.\n" + No_API

        self._log_initial_steps(task)
        # 6. Primary LLM model name
        logger.info("Primary LLM model name: %s", primary_model)

        result = self._call(primary_model, text, max_tokens, task, current_files=current_files)
        if result:
            logger.info("Winner: %s | status code: 200", primary_model)
            elapsed = time.time() - self.t_start
            logger.info("Total time taken: %.3fs", elapsed)
            logger.info("----------------------------------------------------------")
            return result

        logger.info("Primary model failed. Fallback LLM model names:")
        fallback_models = []
        if self.gemini_key:
            fallback_models.extend(self.models.get("fallback_with_gemini", []))
        if self.openrouter_key:
            fallback_models.extend(self.models.get(fallback_key, []))
            
        for m in fallback_models:
            logger.info(" - %s", m)

        winner = None
        for model in self.models.get("fallback_with_gemini", []):
            if not self.gemini_key:
                break
            logger.info("Trying Gemini fallback: %s", model)
            result = self._call(model, text, max_tokens, task, current_files=current_files)
            if result:
                logger.info("Winner: fallback model: %s | status code: 200", model)
                winner = model
                break
            else:
                logger.info("Gemini fallback model %s failed | status code: error/timeout", model)

        if not winner:
            for model in self.models.get(fallback_key, []):
                if not self.openrouter_key:
                    break
                logger.info("Trying OpenRouter fallback: %s", model)
                result = self._call(model, text, max_tokens, task, current_files=current_files)
                if result:
                    logger.info("Winner: fallback model: %s | status code: 200", model)
                    winner = model
                    break
                else:
                    logger.info("OpenRouter fallback model %s failed | status code: error/timeout", model)

        elapsed = time.time() - self.t_start
        logger.info("Total time taken: %.3fs", elapsed)
        logger.info("----------------------------------------------------------")
        if winner and result:
            return result
        return "All models failed. Please try again later."

    # =========================================================================
    # PUBLIC HANDLERS
    # Each handler wraps its core logic in try/except and delegates error
    # formatting to _safe_error() so the right level of detail is shown.
    # =========================================================================

    def _enrich_with_web_search(self, text: str, task: str) -> str:
        import concurrent.futures
        from backend.models_task.web_search import _search_duckduckgo, _search_wikipedia, _summarise_with_gemini, _plain_summary
        from backend.models_task.query_rewriter import rewrite_query_for_search
        
        gemini_key = getattr(self, "gemini_key", "") or ""
        chat_history = self._get_limited_history(task)
        
        timeout_val = 4.0 if getattr(self, "is_fast", False) else 10.0
        
        ddg_results = []
        wiki_summary = ""
        rewritten_query = text
        
        # Start 3 parallel tasks
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_ddg = executor.submit(_search_duckduckgo, text, 5)
            future_wiki = executor.submit(_search_wikipedia, text, 5)
            future_preprocess = executor.submit(rewrite_query_for_search, text, chat_history, gemini_key)
            
            try:
                ddg_results = future_ddg.result(timeout=timeout_val)
            except Exception as e:
                logger.error("[web_search_enrich] DDG failed: %s", e)
                
            try:
                wiki_summary = future_wiki.result(timeout=timeout_val)
            except Exception as e:
                logger.error("[web_search_enrich] Wiki failed: %s", e)
                
            try:
                rewritten_query = future_preprocess.result(timeout=timeout_val)
            except Exception as e:
                logger.error("[web_search_enrich] Preprocess failed: %s", e)
                rewritten_query = text
                
        # Merge available results using the summarizer
        if gemini_key:
            try:
                answer = _summarise_with_gemini(rewritten_query, ddg_results, wiki_summary, gemini_key)
            except Exception as e:
                logger.error("[web_search_enrich] Gemini summary failed: %s", e)
                answer = _plain_summary(rewritten_query, ddg_results, wiki_summary)
        else:
            answer = _plain_summary(rewritten_query, ddg_results, wiki_summary)

        if answer and not answer.startswith("No results"):
            system_note = (
                "System Instruction: Below is some retrieved Live Data related to the user query.\n"
                "1. If the user message needs live or current data, use this Live Data to answer.\n"
                "2. Otherwise, ignore the Live Data and reply normally.\n"
                "3. If you use the Live Data, do NOT mention 'Wikipedia', 'DuckDuckGo', search results, or provide any URLs/links unless the user explicitly asks for them."
            )
            return f"{system_note}\n\nLive Data:\n{answer}\n\nUser Message: {text}"
            
        return text

    def _agentic_search_check(self, user_text: str) -> str | None:
        """
        Ultra-fast Pre-Router / Orchestrator.
        Uses the fastest available model to determine if the query needs a web search.
        Returns the specific search query if needed, else None.
        """
        from backend.utils import is_greeting_or_smalltalk
        if is_greeting_or_smalltalk(user_text):
            return None

        keys_to_try = []
        if getattr(self, "groq_key", None):
            keys_to_try.append(("groq", self.groq_key))
        if getattr(self, "gemini_key", None):
            keys_to_try.append(("gemini", self.gemini_key))
        if getattr(self, "openrouter_key", None):
            keys_to_try.append(("openrouter", self.openrouter_key))
        
        if not keys_to_try:
            return None
            
        prompt = (
            "You are an intent classification engine. Read the user's message.\n"
            "Does the user's message require a live web search to answer accurately (e.g., latest news, current events, recent releases, live prices, or real-time facts)?\n"
            "If YES: Output ONLY the exact search query you would use. Do not explain.\n"
            "If NO: Output exactly the word 'NONE'."
        )
        
        provider, key = keys_to_try[0]
        try:
            if provider == "groq":
                import requests
                r = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_text}
                        ],
                        "temperature": 0.0,
                        "max_tokens": 50,
                    },
                    timeout=2.0
                )
                if r.status_code == 200:
                    ans = r.json()["choices"][0]["message"]["content"].strip()
                    return ans if ans.upper() != "NONE" else None
            elif provider == "gemini":
                from google import genai
                client = genai.Client(api_key=key)
                r = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[
                        {"role": "user", "parts": [{"text": prompt + "\n\nUser Message: " + user_text}]}
                    ],
                    config={"temperature": 0.0, "max_output_tokens": 50}
                )
                ans = r.text.strip()
                return ans if ans.upper() != "NONE" else None
            elif provider == "openrouter":
                import requests
                r = requests.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={
                        "model": "meta-llama/llama-3-8b-instruct:free",
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": user_text}
                        ],
                        "temperature": 0.0,
                        "max_tokens": 50,
                    },
                    timeout=3.0
                )
                if r.status_code == 200:
                    ans = r.json()["choices"][0]["message"]["content"].strip()
                    return ans if ans.upper() != "NONE" else None
        except Exception as e:
            logger.warning(f"Orchestrator failed: {e}")
            return None
        return None

    def handle_text(self, text: str) -> str:
        """Handle general text chat with NLP-adaptive token budget."""
        try:
            # 1. Agentic Orchestrator Check
            search_query = self._agentic_search_check(text)
            if search_query:
                logger.info(f"Agentic Orchestrator triggered search: {search_query}")
                return self.handle_websearch(text, search_query=search_query)

            enriched_text = text
            max_tok = self._smart_token_budget("text_chat")
            if getattr(self, 'is_fast', False):
                from backend.fast import run_fast_route
                return run_fast_route(self, enriched_text, max_tokens=max_tok, task="text_chat")
            return self._with_fallback(
                self.models["text_chat"],
                enriched_text,
                max_tokens=max_tok,
                task="text_chat",
            )
        except Exception as e:
            return self._safe_error(e, "handle_text")

    def handle_coding(self, text: str) -> str:
        """Handle coding/programming requests with full token budget."""
        try:
            if getattr(self, 'is_fast', False):
                from backend.fast import run_fast_route
                return run_fast_route(self, text, max_tokens=self._TOKEN_BUDGETS["coding"], task="coding")
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
            enriched_text = text
            max_tok = self._smart_token_budget("voice")
            if getattr(self, 'is_fast', False):
                from backend.fast import run_fast_route
                return run_fast_route(self, enriched_text, max_tokens=max_tok, task="voice")
            return self._with_fallback(
                self.models["voice_chat"],
                enriched_text,
                max_tokens=max_tok,
                task="voice",
            )
        except Exception as e:
            return self._safe_error(e, "handle_voice_chat")

    def handle_voice_message(self, text: str) -> str:
        """Handle inline mic voice messages routed through the normal chat thread."""
        try:
            enriched_text = text
            max_tok = self._smart_token_budget("voice")
            if getattr(self, 'is_fast', False):
                from backend.fast import run_fast_route
                return run_fast_route(self, enriched_text, max_tokens=max_tok, task="voice")
            return self._with_fallback(
                self.models["voice_chat"],
                enriched_text,
                max_tokens=max_tok,
                task="voice",
            )
        except Exception as e:
            return self._safe_error(e, "handle_voice_message")

    def handle_websearch(self, text: str, search_query: str = None) -> str:
        """
        Web search handler.

        Flow:
          1. perform_web_search() fetches DuckDuckGo + Wikipedia results
             and asks Gemini to summarise them into a clean answer.
          2. On failure (no keys / network error / no results) fall back
             to a plain LLM call with the WEB_SEARCH_PROMPT.
        """
        try:
            query_to_search = search_query if search_query else text
            logger.info("[handle_websearch] query=%r", query_to_search[:80])
            
            from backend.utils import is_greeting_or_smalltalk
            if search_query is not None and is_greeting_or_smalltalk(query_to_search):
                logger.info("[handle_websearch] query is conversational greeting/small talk. Bypassing background search.")
                max_tok = self._smart_token_budget("text_chat")
                if getattr(self, 'is_fast', False):
                    from backend.fast import run_fast_route
                    return run_fast_route(self, text, max_tokens=max_tok, task="text_chat")
                return self._with_fallback(
                    self.models["text_chat"], text, max_tokens=max_tok, task="text_chat"
                )

            chat_history = self._get_limited_history("web_search")
            answer, rewritten_query = perform_web_search(
                query_to_search, 
                gemini_key=self.gemini_key or "",
                chat_history=chat_history
            )

            if answer and not answer.startswith("No results"):
                logger.info("[handle_websearch] Web search successfully retrieved context")
                enriched_text = f"Web Search Results:\n{answer}\n\nUser Query: {rewritten_query}"
            else:
                logger.info("[handle_websearch] Web search returned no results")
                enriched_text = rewritten_query

            max_tok = self._smart_token_budget("web_search")
            if getattr(self, 'is_fast', False):
                from backend.fast import run_fast_route
                return run_fast_route(self, enriched_text, max_tokens=max_tok, task="web_search")
            return self._with_fallback(
                self.models["web_search"], enriched_text, max_tokens=max_tok, task="web_search"
            )
        except Exception as e:
            return self._safe_error(e, "handle_websearch")

    def handle_zeno_plus(self, text: str) -> str:
        try:
            logger.info("[handle_zeno_plus] query=%r", text[:80])
            max_tok = self._smart_token_budget("zeno_plus")
            from backend.fast import run_fast_route
            return run_fast_route(self, text, max_tokens=max_tok, task="zeno_plus")
        except Exception as e:
            return self._safe_error(e, "handle_zeno_plus")

    def handle_zeno_eco(self, text: str) -> str:
        try:
            logger.info("[handle_zeno_eco] query=%r", text[:80])
            max_tok = self._smart_token_budget("zeno_eco")
            if getattr(self, 'is_fast', False):
                from backend.fast import run_fast_route
                return run_fast_route(self, text, max_tokens=max_tok, task="zeno_eco")
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
                from backend.fast import run_fast_route
                return run_fast_route(self, text, max_tokens=max_tok, task="zeno_voice")
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

            temp_files_info = []
            SUPPORTED_EXTS = {'.pdf', '.docx', '.doc', '.txt'}

            for file_obj in files_data:
                name     = file_obj.get('name', 'unknown_file')
                data_url = file_obj.get('dataUrl', '')

                if not data_url or "," not in data_url:
                    results.append(f"Could not read data for file: **{name}**")
                    continue

                ext = os.path.splitext(name)[1].lower()

                if ext not in SUPPORTED_EXTS:
                    results.append(f"**{name}** is not supported. Please upload a PDF, DOCX, DOC, or TXT file.")
                    continue

                needs = {'.pdf': 'pdfplumber', '.docx': 'python-docx', '.doc': 'python-docx'}
                required = needs.get(ext)
                if required and required in missing_libs:
                    results.append(f"Cannot process **{name}**: `{required}` is not installed. Run: `pip install {required}`")
                    continue

                try:
                    header, encoded = data_url.split(",", 1)
                    file_data = base64.b64decode(encoded)

                    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
                        tf.write(file_data)
                        temp_path = tf.name
                    
                    temp_files_info.append((temp_path, name))

                except Exception as e:
                    logger.exception("File decoding error for %s", name)
                    results.append(f"Error reading **{name}**: {str(e)}")

            if temp_files_info:
                try:
                    ans = handler.process_multiple_files(temp_files_info, text)
                    if results:
                        ans = "\n\n".join(results) + "\n\n" + ans
                    return ans
                finally:
                    for temp_path, _ in temp_files_info:
                        try:
                            os.remove(temp_path)
                        except OSError:
                            pass

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
        elif mode == 'zeno_eco':
            prompt = Baymax.ZENO_ECO_PROMPT
        elif mode == 'zeno_plus':
            prompt = Baymax.ZENO_PLUS_PROMPT
        elif mode == 'zeno_voice':
            prompt = Baymax.ZENO_VOICE_PROMPT
        elif mode == 'zeno_shadow':
            prompt = Baymax.ZENO_SHADOW_PROMPT
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

        if mode not in ['zeno_eco', 'zeno_plus', 'zeno_voice', 'zeno_shadow']:
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
