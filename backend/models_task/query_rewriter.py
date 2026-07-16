import logging
import requests

logger = logging.getLogger("hero_ai.query_rewriter")

def rewrite_query_for_search(query: str, chat_history: list, gemini_key: str = None) -> str:
    """
    Rewrites the user query based on the chat history to resolve pronouns
    and vague references for better web search results.
    """
    if not chat_history:
        logger.debug("[query_rewriter] Missing context, skipping rewrite.")
        return query

    # Format history concisely
    history_lines = []
    for msg in chat_history:
        role = "User" if msg.get("role") == "user" else "AI"
        content = msg.get("content", "").strip()
        if content:
            history_lines.append(f"{role}: {content}")
    
    history_text = "\n".join(history_lines)

    prompt = f"""You are an intelligent search query rewriter. 
Your task is to rewrite the latest user query into a standalone, concise web search query.
Resolve any pronouns or vague references (e.g. "that movie", "he") using the recent chat history.
If the query is already clear and self-contained, return it exactly as is. 
Do not answer the query, ONLY return the rewritten query. Keep it short and search-friendly.

Recent Chat History:
{history_text}

Latest user query: {query}

Rewritten search query:"""

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={gemini_key}"
    
    if gemini_key:
        try:
            r = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 60,
                    },
                },
                timeout=5,
            )
            if r.status_code == 200:
                text = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                if text:
                    text = text.strip('"\'* \n')
                    logger.info(f"[query_rewriter] Original: {query!r} -> Rewritten: {text!r}")
                    return text
            else:
                logger.error(f"[query_rewriter] Gemini failed with status {r.status_code}")
        except Exception as e:
            logger.error(f"[query_rewriter] Failed to rewrite query with Gemini: {e}")
            
    # Fallback to HuggingFace if no Gemini key OR Gemini request failed
    import os
    hf_token = (
        os.environ.get("HUGGINGFACE_TOKEN_1") or 
        os.environ.get("HUGGINGFACE_TOKEN_2") or 
        os.environ.get("HUGGINGFACE_TOKEN_3") or
        os.environ.get("HF_TOKEN_1") or
        os.environ.get("HF_TOKEN_2") or
        os.environ.get("HF_TOKEN_3")
    )
    if hf_token:
        hf_url = "https://router.huggingface.co/v1/chat/completions"
        try:
            r = requests.post(
                hf_url,
                headers={
                    "Authorization": f"Bearer {hf_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "meta-llama/Llama-3.3-70B-Instruct",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 60,
                    "temperature": 0.1
                },
                timeout=5,
            )
            if r.status_code == 200:
                text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if text:
                    text = text.strip('"\'* \n')
                    logger.info(f"[query_rewriter] HF Original: {query!r} -> Rewritten: {text!r}")
                    return text
            else:
                logger.error(f"[query_rewriter] HF failed with status {r.status_code}")
        except Exception as e:
            logger.error(f"[query_rewriter] Failed to rewrite query with HF: {e}")

    logger.info(f"[query_rewriter] Fallback to original: {query!r}")
    return query
