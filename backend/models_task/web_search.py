"""
web_search.py (FIXED)
─────────────────────────────────
Searches DuckDuckGo and Wikipedia directly,
then sends the raw results to Gemini for a clean summarised answer.
Includes context-aware query rewriting.

Dependencies:
    pip install duckduckgo-search wikipedia requests
"""

import logging
import requests

try:
    from .query_rewriter import rewrite_query_for_search
except ImportError:
    # Fallback for direct execution/testing
    try:
        from query_rewriter import rewrite_query_for_search
    except ImportError:
        def rewrite_query_for_search(query, chat_history, gemini_key=None):
            return query

logger = logging.getLogger("hero_ai.web_search")


# ── DuckDuckGo ────────────────────────────────────────────────────────────────

def _search_duckduckgo(query: str, max_results: int = 5) -> list[dict]:
    """Return a list of {title, url, snippet} dicts from DuckDuckGo."""
    try:
        # from ddgs import DDGS
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href",  ""),
                    "snippet": r.get("body",  ""),
                })
        return results
    except Exception as e:
        logger.error(f"[web_search] DuckDuckGo error: {e}")
        return []


# ── Wikipedia ─────────────────────────────────────────────────────────────────

def _search_wikipedia(query: str, sentences: int = 5) -> str:
    """Return a short Wikipedia summary string, or '' on failure."""
    try:
        import wikipedia
        wikipedia.set_lang("en")
        return wikipedia.summary(query, sentences=sentences, auto_suggest=True)
    except Exception as e:
        logger.error(f"[web_search] Wikipedia error: {e}")
        return ""


# ── Gemini summariser ─────────────────────────────────────────────────────────

def _summarise_with_gemini(
    query: str,
    ddg_results: list[dict],
    wiki_summary: str,
    gemini_key: str,
) -> str:
    """Feed raw search data into Gemini and return a clean answer."""

    context_parts = []

    if wiki_summary:
        context_parts.append(f"=== Wikipedia ===\n{wiki_summary}")

    if ddg_results:
        lines = []
        for i, r in enumerate(ddg_results, 1):
            lines.append(
                f"{i}. {r['title']}\n   {r['snippet']}\n   Source: {r['url']}"
            )
        context_parts.append("=== Web Results (DuckDuckGo) ===\n" + "\n\n".join(lines))

    if not context_parts:
        return "No search results were found for your query."

    context = "\n\n".join(context_parts)

    prompt = (
        f"You are Baymax, an expert research assistant specializing in information synthesis.\n\n"
        f"User Query: \"{query}\"\n\n"
        f"SEARCH RESULTS:\n{context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Analyze & Extract**: Scrutinize the search results above to identify the most accurate and relevant information for the user's query.\n"
        f"2. **Accuracy & Relevance**: Prioritize factual correctness and direct relevance.\n"
        f"3. **Structure**: Provide a clear, concise, and complete answer. Include supporting details or context only where necessary.\n"
        f"4. **Citations**: At the end of your response, list the URLs or titles of the sources you used.\n\n"
        f"Deliver a professional and helpful response that directly addresses the user's intent."
    )

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={gemini_key}"
    )

    try:
        r = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.4,
                    "maxOutputTokens": 1024,
                    "topP": 0.9,
                },
            },
            timeout=15,
        )
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip()
    except Exception as e:
        logger.error(f"[web_search] Gemini summarization error: {e}")

    return _plain_summary(query, ddg_results, wiki_summary)


def _plain_summary(query: str, ddg_results: list[dict], wiki_summary: str) -> str:
    """Fallback plain-text answer when Gemini is unavailable."""
    parts = [f"Here is what I found for: {query}\n"]
    if wiki_summary:
        parts.append(f"Wikipedia:\n{wiki_summary}\n")
    for r in ddg_results[:3]:
        parts.append(f"• {r['title']}\n  {r['snippet']}\n  {r['url']}")
    return "\n".join(parts) if len(parts) > 1 else "No results found."


# ── Public entry point ────────────────────────────────────────────────────────

def perform_web_search(
    query: str,
    gemini_key: str = "",
    chat_history: list = None,
) -> tuple:
    """
    Search DuckDuckGo + Wikipedia, then summarise with Gemini.
    Returns (answer, rewritten_query).
    """
    rewritten_query = query
    
    # Attempt query rewriting if context exists
    if chat_history and gemini_key:
        try:
            logger.info(f"[web_search] Attempting query rewrite: {query!r}")
            rewritten_query = rewrite_query_for_search(
                query=query, 
                chat_history=chat_history, 
                gemini_key=gemini_key
            )
        except Exception as e:
            logger.error(f"[web_search] Query rewrite failed: {e}")
            # Fallback to original query on error
            rewritten_query = query
    
    logger.info(f"[web_search] Final Search Query: {rewritten_query}")

    ddg_results  = _search_duckduckgo(rewritten_query, max_results=5)
    wiki_summary = _search_wikipedia(rewritten_query, sentences=5)

    if gemini_key:
        answer = _summarise_with_gemini(rewritten_query, ddg_results, wiki_summary, gemini_key)
    else:
        answer = _plain_summary(rewritten_query, ddg_results, wiki_summary)
    
    return answer, rewritten_query