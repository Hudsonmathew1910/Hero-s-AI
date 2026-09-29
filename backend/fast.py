
import time
import logging
import concurrent.futures
from backend.hero_model import ProviderError, ModelError

logger = logging.getLogger("hero_ai.fast")

def run_fast_route(
    baymax_instance,
    text: str,
    max_tokens: int,
    task: str = "text_chat",
    fallback_key: str = "fallback"
) -> str:
    baymax_instance._log_initial_steps(task)
    
    is_router = "CRITICAL INSTRUCTION: If the user's query requires current" in text
    
    from django.conf import settings
    env_gemini = getattr(settings, "GEMINI_API_KEY", None)
    env_or = getattr(settings, "OPENROUTER_API_KEY", None)
    env_groq = getattr(settings, "GROQ_API_KEY", None)
    
    user_gemini = baymax_instance.gemini_key or (baymax_instance.gemini_keys[0] if hasattr(baymax_instance, 'gemini_keys') and baymax_instance.gemini_keys else None)
    user_or = baymax_instance.openrouter_key
    user_groq = baymax_instance.groq_key
    
    list_gemini = baymax_instance.models.get("fallback_with_gemini", [])
    list_or = baymax_instance.models.get(fallback_key, [])
    list_groq = baymax_instance.models.get("fallback_with_groq", [])
    
    # In fast mode, we have parallel groups
    # Group 1: User APIs
    # Group 2: Env APIs
    # Group 3: Env APIs (retry)
    
    groups = [
        [
            ("gemini", list_gemini, user_gemini, "USER"),
            ("openrouter", list_or, user_or, "USER"),
            ("groq", list_groq, user_groq, "USER")
        ],
        [
            ("gemini", list_gemini, env_gemini, "ENV"),
            ("openrouter", list_or, env_or, "ENV"),
            ("groq", list_groq, env_groq, "ENV")
        ],
        [
            ("gemini", list_gemini, env_gemini, "ENV"),
            ("openrouter", list_or, env_or, "ENV"),
            ("groq", list_groq, env_groq, "ENV")
        ]
    ]
    
    def run_provider(provider, models, api_key, key_type):
        if not api_key or not models:
            raise Exception(f"No key or models for {provider}")
        
        # We try models sequentially inside the parallel provider thread
        for model in models:
            try:
                logger.info(f"[Fast] {provider.capitalize()} | {key_type}_KEY | model={model} started")
                t_start = time.time()
                res = baymax_instance._call(model, text, max_tokens, task, None, provider, api_key)
                if res:
                    logger.info(f"[Fast] {provider.capitalize()} SUCCESS | {model} | {time.time()-t_start:.2f}s")
                    return res
            except ModelError as e:
                logger.info(f"[Fast] ERROR | {provider} model_error | {e}")
                continue
            except ProviderError as e:
                logger.info(f"[Fast] ERROR | {provider} provider_error | {e}")
                break
        raise Exception(f"All models failed for {provider}")
    
    for group_idx, group in enumerate(groups):
        futures = []
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        valid_tasks = 0
        for provider, models, api_key, key_type in group:
            if api_key and models:
                valid_tasks += 1
                futures.append(executor.submit(run_provider, provider, models, api_key, key_type))
                
        if valid_tasks == 0:
            continue
            
        logger.info(f"[Fast] Starting parallel group {group_idx + 1}")
        
        winner_res = None
        for future in concurrent.futures.as_completed(futures):
            try:
                res = future.result()
                if res and not winner_res:
                    winner_res = res
                    # Shutdown executor immediately without waiting for others
                    executor.shutdown(wait=False, cancel_futures=True)
                    logger.info("[Fast] Returning first successful response")
                    return winner_res
            except Exception as e:
                pass
                
        # If we got here, all futures in this group failed
        logger.info(f"[Fast] All providers in group {group_idx + 1} failed")
        
    return "All fast models failed. Please try again later."
