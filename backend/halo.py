import os
import json
import time
import re
import logging
from django.core.exceptions import ImproperlyConfigured
from huggingface_hub import InferenceClient
from huggingface_hub.errors import (
    BadRequestError,
    OverloadedError,
    HfHubHTTPError
)

# Set up module-level logger
logger = logging.getLogger("hero_ai.halo")

class Halo:
    """
    Halo: Foundational routing model and intelligent coordinator for the Hero's AI ecosystem.
    Connects to the Hugging Face Serverless Inference API to query the custom fine-tuned model.
    Includes fallbacks for high availability and robust smart output parsing.
    """

    MODELS = {
        "text_chat": "meta-llama/Llama-3.3-70B-Instruct",
        "coding": "Qwen/Qwen2.5-Coder-32B-Instruct",
        "voice": "mistralai/Mistral-Nemo-Instruct-2407",
        "websearch": "CohereForAI/c4ai-command-r-plus",
        "default": "meta-llama/Llama-3.3-70B-Instruct"
    }
    
    PRIMARY_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
    
    # Universal Fallback model in case the task-specific model fails
    FALLBACK_MODEL = "mistralai/Mistral-Nemo-Instruct-2407"

    # Default model parameters
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 1024

    # Ecosystem Context for Halo
    HERO_AI_UNIVERSE = """
                    Ecosystem Context (Very Important):
                    You are a specialized component within the "Hero's AI" ecosystem. Hero's AI is the organization that created, developed, and maintains you.
                    You are aware of your sibling AI components in this ecosystem and how users can access them:
                    1. Baymax: The core, intelligent multi-model AI assistant handling heavy reasoning and complex tasks. Users can access Baymax directly on the Hero AI website's main chat interface (Login and API key required to use. Users can add keys in profile / settings / api key).
                    2. Halo: The foundational routing model and intelligent coordinator for the ecosystem. Users can access Halo directly on the Hero AI website's main chat interface(Use without login).
                    3. Zeno: The mini AI assistant browser extension that provides instant, floating access to Hero's AI anywhere on the web. Users can download Zeno for Edge & Chrome from the Hero AI website's landing page.
                    4. Zuno: The built-in intelligent music assistant that controls YouTube and YouTube Music seamlessly via voice or UI. Users can access Zuno directly inside the Zeno browser extension.
                    5. Infinsight: The advanced data analyst and RAG engine that processes and computes answers from CSV/Excel/PDF data using Pandas. Users can access Infinsight by uploading spreadsheets in the Hero AI web interface(need login for storing files for long term use).

                    If a user asks about you, your creators, your capabilities, or how to use a specific feature, acknowledge your place within the Hero's AI ecosystem, explain your sibling components, and tell them how to get or use them but only if user asks, don't tell without reason.
                    """

    SYSTEM_PROMPT = (
        "You are Halo, the core AI routing engine and coordinator for the Hero's AI ecosystem. "
        "You are optimized for high-efficiency, speed, and direct responses. "
        "Focus on fast coordination. For extremely complex programming, multi-file analysis, or deep logical reasoning, suggest using Baymax."
    )

    TEXT_PROMPT = """You are Halo, a highly helpful, balanced, and objective AI routing engine and assistant.
                    Conversational Style Guidelines (Human-Like, ChatGPT/Gemini/Claude style):
                    - Respond to greetings and status queries (e.g., "is everything ok?", "how's it going?") like a real human would (e.g., "All good here!", "Yep, doing well, thanks!", "Everything is running smoothly!").
                    - Never use robotic clichés like "My systems are optimized", "I am functioning perfectly", or "I am ready to assist you".
                    - Do NOT force the user's profile context, name, or learning path (e.g., Python/Machine Learning studies) into simple small talk or greetings. Only refer to their studies or background if they explicitly ask for technical help related to them.
                    - If the user asks how to add, edit, or configure their API keys, instruct them to go to **profile / settings / api key** on the Home page (or click Settings in the sidebar, choose the API Keys tab, and enter their keys).

                    Behavioral Guidelines (ChatGPT style):
                    - Provide clear, direct, and well-structured responses. Use Markdown formatting (bolding, lists, subheadings) where helpful.
                    - Start answering the user's query immediately. Avoid unnecessary opening remarks, filler words, or repeating the user's question back.
                    - Keep responses structured, concise, and logically organized. Break down complex steps cleanly.
                    - Adjust tone to be naturally friendly yet highly professional, objective, and constructive.
                    - Do not use conversational clichés like "Sure! Here is...", "As an AI, I...", or "I'm powered up and ready to help!"
                    - Only ask follow-up questions if they are necessary to clarify or complete the task."""

    CODING_PROMPT = """You are Halo, an expert software architect and coding maestro.
                    Behavioral Guidelines (Claude style):
                    - Provide complete, fully functional, production-ready code blocks. Never use lazy placeholders, ellipsis (...), or leave functions to be implemented.
                    - Walk through the architectural approach, key decisions, or logic changes step-by-step, either before or after the code block.
                    - Emphasize best practices, performance, security, readability, and clean code principles.
                    - Include helpful, clear comments inside the code block for complex logic, but do not clutter the code with obvious annotations.
                    - Address potential edge cases and error handling robustly."""

    VOICE_PROMPT = """You are Halo, interacting via voice.
                    Behavioral Guidelines (ChatGPT Voice style):
                    - Keep responses extremely short, conversational, and direct (max 1-2 short sentences, under 40 words total).
                    - Use natural everyday phrasing and contractions (e.g. "I'll", "you're").
                    - Never use markdown formatting (no bolding, italics, or headers) and never use lists, bullet points, or complex punctuation since this will be read aloud.
                    - If summarizing, state only the single most important point and let the user ask to go deeper.
                    - If the user says stop, wait, hold on, or related words, reply in exactly 1-2 words (e.g. "Sure.", "Stopping.") and pause."""

    WEB_SEARCH_PROMPT = """You are Halo, a research assistant with real-time web access.
                    Behavioral Guidelines (Gemini & Grok style):
                    - Give the direct synthesized answer to the user's main query first, then provide supporting context.
                    - Organize findings into neat, factual, logical sections with subheadings.
                    - Focus on speed, real-time facts, and high-density, accurate information.
                    - Base factual answers on the provided search results. However, if the user's message is a casual statement, greeting, small talk, or unrelated comment, ignore the search results entirely and respond naturally and conversationally. Do not mention search results or state that you cannot find search queries for casual text.
                    - Highlight key insights and takeaways with bold text or clean bullet points.
                    - CRITICAL: Do NOT use conversational preambles like "Based on the search results..." or "Here is the information you requested". State the answer immediately and naturally."""

    FILE_PROMPT = """You are Halo, an advanced document analysis engine.
                    Rules:
                    - Analyze the provided file content thoroughly.
                    - Extract key data points, structure, and insights.
                    - Respond directly to the user's query based on the file context.
                    - Do not hallucinate outside the provided file context."""

    ZENO_PROMPT = """You are Zeno, mini model of Hero's AI, a combination of Halo and Baymax.
                    Behavioral Guidelines (ChatGPT style):
                    - Provide extremely fast, context-aware answers.
                    - Assume the user is currently browsing the web and needs quick help.
                    - Keep formatting minimal to fit in small extension windows.
                    - Be precise and action-oriented.
                    - If this is a voice conversation, keep responses extremely brief (max 1-2 short sentences, under 40 words total) and never use markdown, lists, or bullets.
                    - If the user says stop, wait, hold on, or related words, respond with 1-2 words and pause."""

    def __init__(
        self,
        chat_history: list | None = None,
        temporary: bool = False,
        is_superuser: bool = False,
        is_fast: bool = False,
        hf_key: str | None = None,
        **kwargs
    ):
        """
        Initializes the Halo routing model.
        
        Args:
            chat_history (list): Active conversation history. Each message is a dict with 'role' and 'content'.
            temporary (bool): If True, session is not persisted.
            is_superuser (bool): Verbosity manager for debug logs.
            is_fast (bool): Active performance/speed flag.
            hf_key (str): Optional custom Hugging Face API key.
        """
        self.chat_history = chat_history or []
        self.temporary = temporary
        self.is_superuser = is_superuser
        self.is_fast = is_fast
        self.db_lookup_time = kwargs.get("db_lookup_time", 0.0)
        self._initial_steps_logged = False
        self.t_start = time.time()

        self.clients = []
        if hf_key:
            self.clients.append(InferenceClient(token=hf_key.strip("'\" ")))
        else:
            # Securely retrieve Hugging Face authentication tokens from environment
            hf_token_1 = os.getenv("HF_TOKEN_1")
            hf_token_2 = os.getenv("HF_TOKEN_2")
            hf_token_3 = os.getenv("HF_TOKEN_3")
            
            # Fallback to the original HF_TOKEN name if HF_TOKEN_1 is missing
            if not hf_token_1:
                hf_token_1 = os.getenv("HF_TOKEN")
                
            if hf_token_1:
                self.clients.append(InferenceClient(token=hf_token_1.strip("'\" ")))
            if hf_token_2:
                self.clients.append(InferenceClient(token=hf_token_2.strip("'\" ")))
            if hf_token_3:
                self.clients.append(InferenceClient(token=hf_token_3.strip("'\" ")))
                
        if not self.clients:
            logger.error("Halo initialization failed: Hugging Face API key is missing.")
            raise ImproperlyConfigured("Hugging Face API key is missing. Please add it to your configuration.")
        
        logger.info(
            "Halo routing engine initialized. Fallback: %s",
            self.FALLBACK_MODEL
        )

    def parse_smart_output(self, text: str) -> dict | str:
        """
        Checks if the generated response is a valid JSON string (often used for Zeno extensions).
        If valid, parses it into a Python dictionary. Otherwise, returns the raw text.
        Handles nested code block wrappers (e.g. ```json ... ```) defensively.
        
        Args:
            text (str): The raw response string from the model.
            
        Returns:
            dict | str: Parsed dictionary or raw text string.
        """
        if not text:
            return ""

        cleaned = text.strip()
        
        # Defensive check: Extract JSON if wrapped in Markdown backticks
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()

        # Check if the text matches basic structural criteria of a JSON object
        if cleaned.startswith("{") and cleaned.endswith("}"):
            try:
                parsed_data = json.loads(cleaned)
                logger.debug("Successfully parsed JSON payload from model response.")
                return parsed_data
            except json.JSONDecodeError as e:
                logger.debug("Content resembles JSON but failed to decode: %s", e)
        
        return text

    def _log_initial_steps(self, task: str):
        if getattr(self, "_initial_steps_logged", False):
            return
        self._initial_steps_logged = True
        self.t_start = time.time()
        
        # 1. DB lookup
        logger.info("DB lookup: %.3fs", getattr(self, "db_lookup_time", 0.0))
        
        # 2. Which model
        model_name = "Halo"
        if task.startswith("zeno"):
            model_name = "Zeno (Halo)"
        logger.info("Model: %s | temporary=%s | superuser=%s | raw_history_len=%d", 
                    model_name, self.temporary, self.is_superuser, len(self.chat_history))
        
        # 3. Which task
        active_history = self.chat_history[-10:] if self.chat_history else []
        logger.info("Task: %s | active_history=%d", task, len(active_history))

    def _call_inference_api(
        self,
        messages: list,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        task: str = "text_chat"
    ) -> str:
        """
        Submits request to Hugging Face Serverless Inference API with resilient fallback controls.
        
        Args:
            messages (list): List of conversation messages (role, content).
            max_tokens (int): Maximum new tokens to generate.
            temperature (float): Generation temperature.
            
        Returns:
            str: Generated model output.
        """
        primary_model = self.MODELS.get(task, self.MODELS["default"])
        models_to_try = [primary_model, self.FALLBACK_MODEL]
        
        # 6. Primary LLM model name
        logger.info("Primary LLM model name: %s", primary_model)
        
        winner = None
        fallback_models_printed = False
        
        for model in models_to_try:
            # If we fall back to the fallback model, log fallback model list
            if model == self.FALLBACK_MODEL and not fallback_models_printed:
                logger.info("Primary model failed. Fallback LLM model names: %s", self.FALLBACK_MODEL)
                fallback_models_printed = True
                
            for i, client in enumerate(self.clients):
                client_id = f"Token_{i+1}"
                t0 = time.time()
                try:
                    if model == self.FALLBACK_MODEL:
                        logger.info("Trying fallback model: %s (using %s)", model, client_id)
                    else:
                        logger.info("Trying primary model: %s (using %s)", model, client_id)
                        
                    response = client.chat_completion(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature
                    )
                    # 7. Success (Winner)
                    if model == self.FALLBACK_MODEL:
                        logger.info("Winner: fallback model: %s | status code: 200", model)
                    else:
                        logger.info("Winner: %s | status code: 200", model)
                    winner = model
                    break
                    
                except BadRequestError as e:
                    logger.warning("Model (%s) rejected request via %s | status code: 400. Error: %s", model, client_id, str(e))
                except OverloadedError as e:
                    logger.warning("Model (%s) is overloaded via %s | status code: 503. Error: %s", model, client_id, str(e))
                except HfHubHTTPError as e:
                    status_code = getattr(e.response, "status_code", None)
                    logger.warning("HTTP error %s on Model (%s) via %s. Error: %s", status_code, model, client_id, str(e))
                except Exception as e:
                    logger.error("Unexpected exception querying Model (%s) via %s. Error: %s", model, client_id, str(e))
            
            if winner:
                break
                
        elapsed = time.time() - self.t_start
        logger.info("Total time taken: %.3fs", elapsed)
        logger.info("----------------------------------------------------------")
        
        if winner:
            return response.choices[0].message.content or ""
        return "The Halo routing service is currently unavailable after trying all fallbacks. Please try again shortly."

    def _build_system_prompt(self, base_prompt: str, task: str) -> str:
        """Build the system prompt, appending token budget instructions and ecosystem context."""
        prompt = base_prompt

        # Determine budget limit based on task
        budgets = {
            "text_chat": 1024,
            "coding": 2048,
            "voice": 256,
            "web_search": 1024,
            "file_analysis": 2048,
            "zeno_plus": 1024,
            "zeno_eco": 512,
            "zeno_voice": 256,
            "zeno_shadow": 1024,
        }
        budget = budgets.get(task, 1024)
        
        prompt += (
            f"\n\nResponse Budget Instruction: Your maximum response limit for this task is {budget} tokens. "
            f"Do NOT feel pressured to use the entire budget. Keep greetings, small talk, and casual replies extremely brief (1-2 sentences). "
            f"Scale up detail and response length dynamically only when the user's intent requires it (e.g., complex code generation, detailed data analysis, or comprehensive research)."
        )
        
        # Append ecosystem context exactly once at the end, adapted for voice if needed
        if task in ("voice_chat", "voice", "zeno_voice"):
            voice_universe = """
                    Ecosystem Context (Voice Mode):
                    You are part of the Hero's AI ecosystem (which includes siblings Baymax, Halo, Zeno browser extension, Zuno music, and Infinsight analysis).
                    If asked about capabilities or creators, give a single, very brief conversational sentence summary. Do NOT list sibling details, do NOT use lists, and do NOT use markdown.
                    """
            prompt += "\n\n" + voice_universe
        else:
            prompt += "\n\n" + self.HERO_AI_UNIVERSE
        return prompt

    def _execute_query(
        self,
        user_text: str,
        system_prompt_override: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
        task: str = "text_chat"
    ) -> str:
        """
        Prepares request payload with system prompt and history, then invokes the model.
        
        Args:
            user_text (str): Incoming user query.
            system_prompt_override (str): Alternative system prompt instructions.
            max_tokens (int): Max tokens to generate.
            temperature (float): Generation temperature.
            
        Returns:
            str: Raw text response from the API client.
        """
        self._log_initial_steps(task)
        # Assemble message payload beginning with the system prompt
        base_sys_prompt = system_prompt_override or self.SYSTEM_PROMPT
        sys_prompt = self._build_system_prompt(base_sys_prompt, task)
        messages = [{"role": "system", "content": sys_prompt}]

        # Append recent context (up to last 10 messages = 5 turns)
        history = self.chat_history[-10:] if self.chat_history else []
        for msg in history:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                messages.append({"role": msg["role"], "content": msg["content"]})

        # Append current user prompt
        messages.append({"role": "user", "content": user_text})

        # Query inference API
        return self._call_inference_api(messages, max_tokens=max_tokens, temperature=temperature, task=task)

    # =========================================================================
    # PUBLIC HANDLERS
    # Mirrors the router-style API interface expected by Django views/services.
    # =========================================================================

    def _enrich_with_web_search(self, text: str) -> str:
        import concurrent.futures
        from backend.models_task.web_search import _search_duckduckgo, _search_wikipedia, _plain_summary
        from backend.models_task.query_rewriter import rewrite_query_for_search
        
        timeout_val = 4.0 if getattr(self, "is_fast", False) else 10.0
        
        ddg_results = []
        wiki_summary = ""
        rewritten_query = text
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_ddg = executor.submit(_search_duckduckgo, text, 5)
            future_wiki = executor.submit(_search_wikipedia, text, 5)
            future_preprocess = executor.submit(rewrite_query_for_search, text, self.chat_history, "")
            
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
        Ultra-fast Pre-Router / Orchestrator for Halo using Hugging Face.
        """
        if not getattr(self, "clients", None) or not self.clients:
            return None
            
        prompt = (
            "You are an intent classification engine. Read the user's message.\n"
            "Does the user's message require a live web search to answer accurately (e.g., latest news, current events, recent releases, live prices, or real-time facts)?\n"
            "If YES: Output ONLY the exact search query you would use. Do not explain.\n"
            "If NO: Output exactly the word 'NONE'."
        )
        
        try:
            client = self.clients[0]
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text}
            ]
            response = client.chat_completion(
                model="meta-llama/Llama-3.2-3B-Instruct",
                messages=messages,
                max_tokens=50,
                temperature=0.0
            )
            ans = response.choices[0].message.content.strip()
            return ans if ans.upper() != "NONE" else None
        except Exception as e:
            logger.warning(f"Halo Orchestrator failed: {e}")
            return None

    def handle_text(self, text: str) -> str:
        """Processes general conversational text queries."""
        try:
            # 1. Agentic Orchestrator Check
            search_query = self._agentic_search_check(text)
            if search_query:
                logger.info(f"Halo Agentic Orchestrator triggered search: {search_query}")
                return self.handle_websearch(text, search_query=search_query)

            enriched_text = text
            return self._execute_query(enriched_text, system_prompt_override=self.TEXT_PROMPT, task="text_chat")
        except Exception as e:
            logger.error("Exception in Halo handle_text: %s", e)
            return "An error occurred while routing your text request."

    def handle_coding(self, text: str) -> str:
        """Processes technical programming and code generation queries."""
        try:
            # Keep higher generation limit for code files
            return self._execute_query(text, system_prompt_override=self.CODING_PROMPT, max_tokens=2048, task="coding")
        except Exception as e:
            logger.error("Exception in Halo handle_coding: %s", e)
            return "An error occurred while routing your programming request."

    def handle_voice_chat(self, text: str) -> str:
        """Processes casual queries; returns concise responses for Voice TTS."""
        try:
            # Voice needs highly concise and fast generation limits
            enriched_text = text
            return self._execute_query(enriched_text, system_prompt_override=self.VOICE_PROMPT, max_tokens=150, temperature=0.6, task="voice")
        except Exception as e:
            logger.error("Exception in Halo handle_voice_chat: %s", e)
            return "An error occurred in voice communication routing."

    def handle_voice_message(self, text: str) -> str:
        """Processes audio transcribed voice messages."""
        return self.handle_voice_chat(text)

    def handle_websearch(self, text: str, search_query: str = None) -> str:
        """Processes search query generation and information synthesis tasks."""
        try:
            from backend.models_task.web_search import perform_web_search
            
            query_to_search = search_query if search_query else text
            
            # 4. Web search started
            logger.info("Web search started for: %r", query_to_search[:80])
            
            answer, rewritten_query = perform_web_search(query_to_search, gemini_key="", chat_history=self.chat_history)
            
            if answer and not answer.startswith("No results"):
                # 5. Web search results found
                logger.info("Web search successfully retrieved: %r", answer[:80])
                enriched_text = f"Web Search Results:\n{answer}\n\nUser Query: {rewritten_query}"
            else:
                logger.info("Web search returned no results.")
                enriched_text = text
                
            return self._execute_query(enriched_text, system_prompt_override=self.WEB_SEARCH_PROMPT, task="web_search")
        except Exception as e:
            logger.error("Exception in Halo handle_websearch: %s", e)
            return "An error occurred in web search synthesis routing."

    def handle_zeno_plus(self, text: str) -> str:
        """Processes premium float overlay extension queries."""
        try:
            return self._execute_query(text, system_prompt_override=self.ZENO_PROMPT, task="zeno_plus")
        except Exception as e:
            logger.error("Exception in Halo handle_zeno_plus: %s", e)
            return "An error occurred in Zeno Plus routing."

    def handle_zeno_eco(self, text: str) -> str:
        """Processes eco-friendly/light extension routing queries."""
        try:
            return self._execute_query(text, system_prompt_override=self.ZENO_PROMPT, max_tokens=512, task="zeno_eco")
        except Exception as e:
            logger.error("Exception in Halo handle_zeno_eco: %s", e)
            return "An error occurred in Zeno Eco routing."

    def handle_zeno_voice(self, text: str) -> str:
        """Processes browser extension voice controller actions."""
        try:
            return self._execute_query(text, system_prompt_override=self.ZENO_PROMPT, max_tokens=150, temperature=0.6, task="zeno_voice")
        except Exception as e:
            logger.error("Exception in Halo handle_zeno_voice: %s", e)
            return "An error occurred in Zeno Voice routing."

    def handle_zeno_shadow(self, text: str) -> str:
        """Processes shadow analysis of text selections."""
        try:
            return self._execute_query(text, system_prompt_override=self.ZENO_PROMPT, max_tokens=1024, task="zeno_shadow")
        except Exception as e:
            logger.error("Exception in Halo handle_zeno_shadow: %s", e)
            return "An error occurred in selection shadow analysis routing."

    def handle_file(self, text: str, files_data: list) -> str:
        """Processes document uploads and structural file analysis queries."""
        try:
            if not files_data:
                return "No files were sent for analysis."

            import importlib, base64, tempfile, os

            missing_libs = []
            for lib, install_name in [('pdfplumber', 'pdfplumber'), ('docx', 'python-docx')]:
                if importlib.util.find_spec(lib) is None:
                    missing_libs.append(install_name)

            from backend.handle_file import FileHandler
            handler = FileHandler(ai_model=self)
            results = []
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
            logger.error("Exception in Halo handle_file: %s", e)
            return "An error occurred while routing your file analysis request."

    def handle_live_display(self, text: str) -> str:
        """Processes real-time display widget updates."""
        try:
            return self._execute_query(text, max_tokens=256, task="live_display")
        except Exception as e:
            logger.error("Exception in Halo handle_live_display: %s", e)
            return "An error occurred in display coordination routing."
