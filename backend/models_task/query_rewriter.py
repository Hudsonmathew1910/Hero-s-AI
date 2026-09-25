import logging
import requests

logger = logging.getLogger("hero_ai.query_rewriter")

def _parse_rewrite_response(response_text: str) -> tuple[bool, str]:
    """
    Parses the response from the rewriter model.
    Expects JSON: {"live": bool, "query": str}
    """
    import json
    import re
    clean_text = response_text.strip()
    
    # Strip markdown code blocks if present (e.g. ```json ... ```)
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean_text, re.DOTALL)
    if match:
        clean_text = match.group(1)
        
    try:
        data = json.loads(clean_text)
        live = bool(data.get("live", False))
        query = str(data.get("query", "")).strip()
        return live, query
    except Exception:
        pass

    # Regex fallback if JSON parsing fails
    live_match = re.search(r'"live"\s*:\s*(true|false)', clean_text, re.IGNORECASE)
    live = False
    if live_match:
        live = live_match.group(1).lower() == "true"
        
    query_match = re.search(r'"query"\s*:\s*"([^"]*)"', clean_text)
    if query_match:
        return live, query_match.group(1).strip()
        
    # Absolute fallback: treat entire text as query, default to need search (True)
    return True, response_text.strip()

def rewrite_query_for_search(query: str, chat_history: list, gemini_key: str = None, groq_key: str = None) -> tuple[bool, str]:
    """
    Rewrites the user query and determines if it requires live web search data.
    Returns (need_live_data, rewritten_query).
    """
    # Clean single-line slice for logging to avoid printing huge page context
    log_query = query.split('\n')[0]
    if len(log_query) > 100:
        log_query = log_query[:100] + "..."

    # Format history concisely
    for_msg_history = []
    if chat_history:
        for msg in chat_history:
            role = "User" if msg.get("role") == "user" else "AI"
            content = msg.get("content", "").strip()
            if content:
                for_msg_history.append(f"{role}: {content}")
    
    history_text = "\n".join(for_msg_history)

    import datetime
    current_date = datetime.datetime.now().strftime("%A, %B %d, %Y")

    prompt = f"""You are an intelligent search query analyzer and rewriter. 
Today's Date: {current_date}

Your tasks are:
1. **Analyze for Live Data**: Determine if the latest user query requires live, current, real-time web search information (e.g. current events, news, "what is going on", current politicians/officeholders, recent headlines, weather, release dates, stock prices, live data). Set "live" to true if the query is seeking real-time or current information (even if vague like "whats going on" or "latest news"), and false ONLY if it is a static, general educational/coding/historical question or simple greeting that can be answered without a search engine.
2. **Rewrite the Query**: Rewrite the latest user query into a standalone, concise web search query, resolving any pronouns or vague references (e.g., "that movie", "he", "it") using the recent chat history.

Output your response in valid JSON format ONLY, with no extra conversational text or markdown block formatting.
JSON Schema:
{{
  "live": true or false,
  "query": "standalone rewritten search query"
}}

Few-Shot Examples:
Example 1:
User: "Do you know who is the MLA of Thoothukudi?"
Response: {{ "live": true, "query": "current MLA of Thoothukudi" }}

Example 2:
User: "Whats going on in Tamilnadu"
Response: {{ "live": true, "query": "Tamil Nadu news current events" }}

Example 3:
User: "Who is the CM of Tamilnadu?"
Response: {{ "live": true, "query": "current Chief Minister of Tamil Nadu" }}

Example 4:
User: "Explain recursion in Python"
Response: {{ "live": false, "query": "recursion in Python" }}

Example 5:
User: "How is it going"
Response: {{ "live": false, "query": "how is it going" }}

Example 6:
User: "When is the Batman 2 movie release date?"
Response: {{ "live": true, "query": "Batman 2 release date" }}

Example 7:
User: "Who was the first president of USA?"
Response: {{ "live": false, "query": "first president of USA" }}

Recent Chat History:
{history_text}

Latest user query: {query}
"""

    import os
    gemini_keys = []
    if gemini_key:
        gemini_keys.append(gemini_key.strip("'\" "))
    
    gk1 = os.environ.get("Gemini_K1")
    gk2 = os.environ.get("Gemini_K2")
    if gk1:
        gemini_keys.append(gk1.strip("'\" "))
    if gk2:
        gemini_keys.append(gk2.strip("'\" "))

    for idx, gk in enumerate(gemini_keys):
        if not gk:
            continue
        try:
            logger.info(f"[query_rewriter] Attempting Gemini rewrite with key index {idx}")
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent?key={gk}"
            r = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.1,
                        "maxOutputTokens": 100,
                    },
                },
                timeout=5,
            )
            if r.status_code == 200:
                text = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                if text:
                    live, parsed_query = _parse_rewrite_response(text)
                    if not parsed_query:
                        parsed_query = query
                    logger.info(f"[query_rewriter] Gemini success: Original: {log_query!r} -> Live: {live} | Rewritten: {parsed_query!r}")
                    return live, parsed_query
            else:
                logger.error(f"[query_rewriter] Gemini key index {idx} failed with status {r.status_code}")
        except Exception as e:
            logger.error(f"[query_rewriter] Failed to rewrite query with Gemini key index {idx}: {e}")
            
    # Fallback to Groq if no Gemini key OR Gemini request failed
    groq_keys = []
    if groq_key:
        groq_keys.append(groq_key.strip("'\" "))
    
    # Load server environment Groq keys
    g1 = os.environ.get("Groq_1")
    g2 = os.environ.get("Groq_2")
    g_default = os.environ.get("GROQ_API_KEY")
    
    if g1:
        groq_keys.append(g1.strip("'\" "))
    if g2:
        groq_keys.append(g2.strip("'\" "))
    if g_default:
        groq_keys.append(g_default.strip("'\" "))
        
    for i, gk in enumerate(groq_keys):
        if not gk:
            continue
        try:
            logger.info(f"[query_rewriter] Attempting Groq rewrite with key index {i}")
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {gk}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "openai/gpt-oss-20b",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.1
                },
                timeout=5,
            )
            if r.status_code == 200:
                text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if text:
                    live, parsed_query = _parse_rewrite_response(text)
                    if not parsed_query:
                        parsed_query = query
                    logger.info(f"[query_rewriter] Groq success: Original: {log_query!r} -> Live: {live} | Rewritten: {parsed_query!r}")
                    return live, parsed_query
            else:
                logger.error(f"[query_rewriter] Groq key index {i} failed with status {r.status_code}: {r.text}")
        except Exception as e:
            logger.error(f"[query_rewriter] Failed to rewrite query with Groq key index {i}: {e}")

    logger.info(f"[query_rewriter] Fallback to original: {log_query!r}")
    return True, query
