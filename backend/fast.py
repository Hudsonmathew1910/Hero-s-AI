import time
import logging
from backend.hero_model import GroqProviderError, GroqModelError

logger = logging.getLogger("hero_ai.fast")

def run_fast_route(
    baymax_instance,
    text: str,
    max_tokens: int,
    task: str = "text_chat",
    fallback_key: str = "fallback"
) -> str:
    """
    New fast mode routing logic:
    If fast mode is enabled:
      1. Directly use Groq models for fast response.
      2. Query the first Groq model in fallback_with_groq.
         - If it succeeds, return the response.
         - If it fails due to GroqProviderError (auth, traffic, network, HTTP 429, 503, etc.):
           Immediately skip remaining Groq models and jump to the primary model for the task.
           If the primary model fails, run the regular fallbacks (Gemini/OpenRouter lists).
         - If it fails due to GroqModelError (model-specific issue):
           Continue trying the remaining Groq models in fallback_with_groq.
           If all of them fail, fall back to the primary model and regular fallbacks.
    """
    baymax_instance._log_initial_steps(task)
    
    No_API = """
🔑 **API Key Configuration Required**

To start chatting, please configure your API Keys in your Heros profile settings:
1. Log in to your Heros account website.
2. Go to **Settings** / **API Keys**.
3. Add your key (Gemini, OpenRouter, or Groq) and save.

*Your API keys are encrypted and stored securely on the server—they are never exposed to the browser.*
"""
    if not baymax_instance.groq_key:
        if task == "zeno_shadow":
            return "🔑 **Groq API Key Required for Shadow Mode**\n\nPlease add your Groq API key in profile / settings / api key to enable background page summarization.\n" + No_API
        if task == "voice":
            return baymax_instance._with_fallback(primary_model, text, max_tokens, fallback_key, task)
        return "🔑 **Groq API Key Required for Fast Response**\n\nPlease add your Groq API key in profile / settings / api key to enable Fast mode.\n" + No_API

    groq_models = baymax_instance.models.get("fallback_with_groq", [])
    primary_model = baymax_instance.models.get(task)
    if not primary_model:
        # Fallback default if task isn't specifically mapped
        primary_model = 'gemini-3.1-flash-lite'

    if not groq_models:
        logger.warning("No Groq models configured. Reverting to primary model fallback.")
        return baymax_instance._with_fallback(primary_model, text, max_tokens, fallback_key, task)

    # Attempt the first Groq model
    first_model = groq_models[0]
    logger.info("Fast mode: querying first Groq model: %s", first_model)
    
    try:
        res = baymax_instance._call_groq(first_model, text, max_tokens, task)
        if res:
            logger.info("Winner: fallback model: %s | status code: 200", first_model)
            elapsed = time.time() - baymax_instance.t_start
            logger.info("Total time taken: %.3fs", elapsed)
            logger.info("----------------------------------------------------------")
            return res
    except GroqProviderError as e:
        logger.warning(
            "First Groq model failed due to Provider/Traffic error: %s. "
            "Immediately skipping remaining Groq models and falling back to Primary Model: %s.",
            e, primary_model
        )
        return baymax_instance._with_fallback(primary_model, text, max_tokens, fallback_key, task)
    except GroqModelError as e:
        logger.warning(
            "First Groq model failed due to Model-specific error: %s. "
            "Continuing sequentially with remaining Groq fallback models.",
            e
        )
    except Exception as e:
        logger.error(
            "Unexpected exception querying first Groq model: %s. Falling back to Primary Model: %s.",
            str(e), primary_model
        )
        return baymax_instance._with_fallback(primary_model, text, max_tokens, fallback_key, task)

    # Attempt the remaining Groq models sequentially
    for model in groq_models[1:]:
        logger.info("Trying next Groq fallback model: %s", model)
        try:
            res = baymax_instance._call_groq(model, text, max_tokens, task)
            if res:
                logger.info("Winner: fallback model: %s | status code: 200", model)
                elapsed = time.time() - baymax_instance.t_start
                logger.info("Total time taken: %.3fs", elapsed)
                logger.info("----------------------------------------------------------")
                return res
        except Exception as e:
            logger.warning("Groq fallback model %s failed: %s", model, e)

    # If all Groq models failed, use the normal fallback chain
    logger.warning("All Groq models failed. Falling back to Primary Model: %s.", primary_model)
    return baymax_instance._with_fallback(primary_model, text, max_tokens, fallback_key, task)
