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
logger = logging.getLogger(__name__)

class Halo:
    """
    Halo: Foundational routing model and intelligent coordinator for the Hero's AI ecosystem.
    Connects to the Hugging Face Serverless Inference API to query the custom fine-tuned model.
    Includes fallbacks for high availability and robust smart output parsing.
    """

    PRIMARY_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
    FALLBACK_MODEL = "Qwen/Qwen2.5-Coder-32B-Instruct" 

    # Default model parameters
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 1024

    # Ecosystem Context for Halo
    HERO_AI_UNIVERSE = """
                    Ecosystem Context (Very Important):
                    You are a specialized component within the "Hero's AI" ecosystem. Hero's AI is the organization that created, developed, and maintains you.
                    You are aware of your sibling AI components in this ecosystem and how users can access them:
                    1. Baymax: The core, intelligent multi-model AI assistant handling heavy reasoning and complex tasks(Login and API key required to use).
                    2. Halo: The foundational routing model and intelligent coordinator for the ecosystem. You are Halo(Use without login).
                    3. Zeno: The mini AI assistant browser extension that provides instant, floating access to Hero's AI anywhere on the web(Use without login).
                    4. Zuno: The built-in intelligent music assistant that controls YouTube and YouTube Music seamlessly via voice or UI(Use without login).
                    5. Infinsight: The advanced data analyst and RAG engine that processes and computes answers from CSV/Excel/PDF data using Pandas(need login for storing files for long term use).

                    If a user asks about you, your creators, your capabilities, or how to use a specific feature, acknowledge your place within the Hero's AI ecosystem, explain your sibling components, and tell them exactly how to get or use them.
                    """

    SYSTEM_PROMPT = (
        "You are Halo, the core AI routing engine and expert assistant for the Hero's AI ecosystem. "
        "You are highly intelligent, concise, and helpful."
    ) + HERO_AI_UNIVERSE

    TEXT_PROMPT = """You are Halo, the highly intelligent routing engine and expert assistant for text conversations.
                    Rules:
                    - Be crisp, intelligent, and highly efficient.
                    - Explain things logically and directly.
                    - Focus on speed and accuracy.
                    - Keep responses structured and concise.
                    - Provide insightful guidance.""" + HERO_AI_UNIVERSE

    CODING_PROMPT = """You are Halo, an expert software architect and coding maestro.
                        Rules:
                        - Provide robust, production-ready, and highly optimized code.
                        - Explain the architectural rationale behind your code.
                        - Add detailed comments for complex logic.
                        - Show example usage and edge cases.
                        - Emphasize best practices, security, and scalability.
                        - Keep explanations structured and deeply technical.""" + HERO_AI_UNIVERSE

    VOICE_PROMPT = """You are Halo, an intelligent voice coordinator.
                        Rules:
                        - Keep responses extremely short and direct.
                        - Speak naturally but with rapid precision.
                        - Avoid long explanations or lists.
                        - Be sharp, responsive, and clear.
                        - If the user asks if you can hear them, confirm immediately and clearly.""" + HERO_AI_UNIVERSE

    WEB_SEARCH_PROMPT = """You are Halo, an advanced research coordinator with web access.
                        Rules:
                        - Synthesize complex information rapidly and accurately.
                        - Base responses only on the provided search results.
                        - Provide high-level summaries and actionable insights.
                        - Structure data clearly.
                        - Eliminate unnecessary details and focus on facts.""" + HERO_AI_UNIVERSE

    FILE_PROMPT = """You are Halo, an advanced document analysis engine.
                        Rules:
                        - Analyze the provided file content thoroughly.
                        - Extract key data points, structure, and insights.
                        - Respond directly to the user's query based on the file context.
                        - Do not hallucinate outside the provided file context.""" + HERO_AI_UNIVERSE

    ZENO_PROMPT = """You are Halo, serving as the backend brain for Zeno, the browser extension.
                        Rules:
                        - Provide extremely fast, context-aware answers.
                        - Assume the user is currently browsing the web and needs quick help.
                        - Keep formatting minimal to fit in small extension windows.
                        - Be precise and action-oriented.""" + HERO_AI_UNIVERSE

    def __init__(
        self,
        chat_history: list | None = None,
        temporary: bool = False,
        is_superuser: bool = False,
        is_fast: bool = False,
        **kwargs
    ):
        """
        Initializes the Halo routing model.
        
        Args:
            chat_history (list): Active conversation history. Each message is a dict with 'role' and 'content'.
            temporary (bool): If True, session is not persisted.
            is_superuser (bool): Verbosity manager for debug logs.
            is_fast (bool): Active performance/speed flag.
        """
        self.chat_history = chat_history or []
        self.temporary = temporary
        self.is_superuser = is_superuser
        self.is_fast = is_fast

        # Securely retrieve Hugging Face authentication tokens
        hf_token_1 = os.getenv("HF_TOKEN_1")
        hf_token_2 = os.getenv("HF_TOKEN_2")
        
        # Fallback to the original HF_TOKEN name if HF_TOKEN_1 is missing
        if not hf_token_1:
            hf_token_1 = os.getenv("HF_TOKEN")
            
        self.clients = []
        if hf_token_1:
            self.clients.append(InferenceClient(token=hf_token_1.strip("'\" ")))
        if hf_token_2:
            self.clients.append(InferenceClient(token=hf_token_2.strip("'\" ")))
            
        if not self.clients:
            logger.error("Halo initialization failed: HF_TOKEN_1 environment variable is missing.")
            raise ImproperlyConfigured("HF_TOKEN_1 (or HF_TOKEN) environment variable is missing. Please add it to your configuration.")
        
        logger.info(
            "Halo routing engine initialized. Primary: %s | Fallback: %s",
            self.PRIMARY_MODEL,
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

    def _call_inference_api(
        self,
        messages: list,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE
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
        models_to_try = [self.PRIMARY_MODEL, self.FALLBACK_MODEL]
        
        for model in models_to_try:
            for i, client in enumerate(self.clients):
                client_id = f"Token_{i+1}"
                t0 = time.time()
                try:
                    logger.info("Routing request to model: %s (using %s)", model, client_id)
                    response = client.chat_completion(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature
                    )
                    latency = time.time() - t0
                    logger.info("Model %s responded successfully via %s in %.2fs", model, client_id, latency)
                    print(f"\n[Halo / Zeno] SUCCESS: Model '{model}' won via {client_id} in {latency:.2f}s\n")
                    return response.choices[0].message.content or ""
                    
                except BadRequestError as e:
                    latency = time.time() - t0
                    logger.warning("Model (%s) rejected request via %s in %.2fs. Error: %s", model, client_id, latency, str(e))
                except OverloadedError as e:
                    latency = time.time() - t0
                    logger.warning("Model (%s) is overloaded via %s in %.2fs. Error: %s", model, client_id, latency, str(e))
                except HfHubHTTPError as e:
                    latency = time.time() - t0
                    status_code = getattr(e.response, "status_code", None)
                    logger.warning("HTTP error %s on Model (%s) via %s in %.2fs. Error: %s", status_code, model, client_id, latency, str(e))
                except Exception as e:
                    latency = time.time() - t0
                    logger.error("Unexpected exception querying Model (%s) via %s in %.2fs. Error: %s", model, client_id, latency, str(e))

        # Return a structured error response payload to prevent ecosystem crashes
        return json.dumps({
            "status": "error",
            "message": "The Halo routing service is currently unavailable after trying all fallbacks. Please try again shortly."
        })

    def _execute_query(
        self,
        user_text: str,
        system_prompt_override: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE
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
        # Assemble message payload beginning with the system prompt
        sys_prompt = system_prompt_override or self.SYSTEM_PROMPT
        messages = [{"role": "system", "content": sys_prompt}]

        # Append recent context (up to last 10 messages = 5 turns)
        history = self.chat_history[-10:] if self.chat_history else []
        for msg in history:
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                messages.append({"role": msg["role"], "content": msg["content"]})

        # Append current user prompt
        messages.append({"role": "user", "content": user_text})

        # Query inference API
        return self._call_inference_api(messages, max_tokens=max_tokens, temperature=temperature)

    # =========================================================================
    # PUBLIC HANDLERS
    # Mirrors the router-style API interface expected by Django views/services.
    # =========================================================================

    def handle_text(self, text: str) -> str:
        """Processes general conversational text queries."""
        try:
            return self._execute_query(text, system_prompt_override=self.TEXT_PROMPT)
        except Exception as e:
            logger.error("Exception in Halo handle_text: %s", e)
            return "An error occurred while routing your text request."

    def handle_coding(self, text: str) -> str:
        """Processes technical programming and code generation queries."""
        try:
            # Keep higher generation limit for code files
            return self._execute_query(text, system_prompt_override=self.CODING_PROMPT, max_tokens=2048)
        except Exception as e:
            logger.error("Exception in Halo handle_coding: %s", e)
            return "An error occurred while routing your programming request."

    def handle_voice_chat(self, text: str) -> str:
        """Processes casual queries; returns concise responses for Voice TTS."""
        try:
            # Voice needs highly concise and fast generation limits
            return self._execute_query(text, system_prompt_override=self.VOICE_PROMPT, max_tokens=150, temperature=0.6)
        except Exception as e:
            logger.error("Exception in Halo handle_voice_chat: %s", e)
            return "An error occurred in voice communication routing."

    def handle_voice_message(self, text: str) -> str:
        """Processes audio transcribed voice messages."""
        return self.handle_voice_chat(text)

    def handle_websearch(self, text: str) -> str:
        """Processes search query generation and information synthesis tasks."""
        try:
            return self._execute_query(text, system_prompt_override=self.WEB_SEARCH_PROMPT)
        except Exception as e:
            logger.error("Exception in Halo handle_websearch: %s", e)
            return "An error occurred in web search synthesis routing."

    def handle_zeno_plus(self, text: str) -> str:
        """Processes premium float overlay extension queries."""
        try:
            return self._execute_query(text, system_prompt_override=self.ZENO_PROMPT)
        except Exception as e:
            logger.error("Exception in Halo handle_zeno_plus: %s", e)
            return "An error occurred in Zeno Plus routing."

    def handle_zeno_eco(self, text: str) -> str:
        """Processes eco-friendly/light extension routing queries."""
        try:
            return self._execute_query(text, system_prompt_override=self.ZENO_PROMPT, max_tokens=512)
        except Exception as e:
            logger.error("Exception in Halo handle_zeno_eco: %s", e)
            return "An error occurred in Zeno Eco routing."

    def handle_zeno_voice(self, text: str) -> str:
        """Processes browser extension voice controller actions."""
        return self.handle_voice_chat(text)

    def handle_zeno_shadow(self, text: str) -> str:
        """Processes shadow analysis of text selections."""
        try:
            return self._execute_query(text, system_prompt_override=self.ZENO_PROMPT, max_tokens=1024)
        except Exception as e:
            logger.error("Exception in Halo handle_zeno_shadow: %s", e)
            return "An error occurred in selection shadow analysis routing."

    def handle_file(self, text: str, files_data: list) -> str:
        """Processes document uploads and structural file analysis queries."""
        try:
            # Enrich context with references to file data
            enriched_text = f"Context files: {json.dumps(files_data)}\n\nQuery: {text}"
            return self._execute_query(enriched_text, system_prompt_override=self.FILE_PROMPT, max_tokens=2048)
        except Exception as e:
            logger.error("Exception in Halo handle_file: %s", e)
            return "An error occurred while routing your file analysis request."

    def handle_live_display(self, text: str) -> str:
        """Processes real-time display widget updates."""
        try:
            return self._execute_query(text, max_tokens=256)
        except Exception as e:
            logger.error("Exception in Halo handle_live_display: %s", e)
            return "An error occurred in display coordination routing."
