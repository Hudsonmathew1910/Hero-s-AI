import logging
import requests

logger = logging.getLogger("hero_ai.query_rewriter")

def rewrite_query_for_search(query: str, chat_history: list, gemini_key: str = None) -> str:
    """
    Rewrites the user query based on the chat history to resolve pronouns
    and vague references for better web search results.
    """
    if not chat_history or not gemini_key:
        logger.debug("[query_rewriter] Missing context or key, skipping rewrite.")
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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent?key={gemini_key}"
    
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
    except Exception as e:
        logger.error(f"[query_rewriter] Failed to rewrite query: {e}")

    logger.info(f"[query_rewriter] Fallback to original: {query!r}")
    return query
