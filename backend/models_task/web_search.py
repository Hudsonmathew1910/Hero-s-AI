"""
web_search.py (FIXED)
─────────────────────────────────────────────
Searches DuckDuckGo and Wikipedia directly,
then sends the raw results to Gemini for a clean summarised answer.
Includes context-aware query rewriting and rate limit handling.

Dependencies:
    pip install ddgs wikipedia requests lxml beautifulsoup4
"""

import logging
import requests
import time
from bs4 import BeautifulSoup

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

import concurrent.futures
import trafilatura

def _scrape_page(url: str) -> str:
    """Fetch and extract readable text from a URL, truncated to 3000 chars."""
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_links=False, include_images=False)
        if text:
            return text[:3000]
    except Exception as e:
        logger.error(f"[web_search] Trafilatura error scraping {url}: {e}")
    return ""

def _search_duckduckgo(query: str, max_results: int = 5) -> list[dict]:
    """Return a list of {title, url, snippet} dicts from DuckDuckGo, with deep read for top 2."""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title", ""),
                    "url":     r.get("href",  ""),
                    "snippet": r.get("body",  ""),
                })
        
        # Scrape full text for top 2 URLs concurrently
        top_urls = [r["url"] for r in results[:2] if r.get("url")]
        
        if top_urls:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                scraped_texts = list(executor.map(_scrape_page, top_urls))
                
            for i, text in enumerate(scraped_texts):
                if text and len(text) > 50:
                    results[i]["snippet"] = text + "\n[End of full page context]"

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
        wikipedia.set_user_agent("HerosAI/1.0 (hudson@heros.ai)")
        return wikipedia.summary(query, sentences=sentences, auto_suggest=True)
    except wikipedia.exceptions.DisambiguationError as e:
        # When Wikipedia returns a disambiguation page, try the first option
        logger.warning(f"[web_search] Disambiguation page for '{query}', trying first option")
        try:
            if e.options:
                return wikipedia.summary(e.options[0], sentences=sentences, auto_suggest=False)
        except Exception:
            pass
        return ""
    except Exception as e:
        logger.error(f"[web_search] Wikipedia error: {e}")
        return ""


# ── Gemini summariser ─────────────────────────────────────────────────────────

def _summarise_with_gemini(
    query: str,
    ddg_results: list[dict],
    wiki_summary: str,
    gemini_key: str,
) -> str | None:
    """Feed raw search data into Gemini and return a clean answer."""
    from backend.hero_model import Baymax

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
        f"1. **Strict Search Result Fidelity**: Base your answer ONLY and DIRECTLY on the provided SEARCH RESULTS above. Do not use your own training data or general knowledge for facts. If the search results contain the answer, summarize it accurately.\n"
        f"2. **Handle Conflicts**: If there are conflicting facts in the search results, present the most recent and reliable source (e.g. incumbent status or dates).\n"
        f"3. **Direct Output**: Do NOT use conversational preambles like 'Based on the search results...' or 'Here is the answer'. Start your answer immediately and naturally.\n"
        f"4. **Citations**: Always list the URLs or titles of the sources you used from the SEARCH RESULTS at the very end of your response.\n\n"
        f"Deliver a professional response that directly answers the user query using only the provided search results.\n"
        f"{Baymax.HERO_AI_UNIVERSE}"
    )

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
        
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={gk}"
        )

        try:
            logger.info(f"[web_search] Attempting Gemini summarization with key index {idx}")
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
            else:
                logger.error(f"[web_search] Gemini summarization key index {idx} failed with status {r.status_code}")
        except Exception as e:
            logger.error(f"[web_search] Gemini summarization error with key index {idx}: {e}")

    return None

def _summarise_with_groq(
    query: str,
    ddg_results: list[dict],
    wiki_summary: str,
    groq_key: str = "",
) -> str | None:
    """Fallback summarizer using Groq when Gemini is unavailable."""
    context_parts = []
    if wiki_summary:
        context_parts.append(f"=== Wikipedia ===\n{wiki_summary}")
    if ddg_results:
        lines = []
        for i, r in enumerate(ddg_results, 1):
            lines.append(f"{i}. {r['title']}\n   {r['snippet']}\n   Source: {r['url']}")
        context_parts.append("=== Web Results ===\n" + "\n\n".join(lines))
    if not context_parts:
        return None

    context = "\n\n".join(context_parts)
    from backend.hero_model import Baymax
    prompt = (
        f"You are Baymax, an expert research assistant specializing in information synthesis.\n\n"
        f"User Query: \"{query}\"\n\n"
        f"SEARCH RESULTS:\n{context}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. **Strict Search Result Fidelity**: Base your answer ONLY and DIRECTLY on the provided SEARCH RESULTS above. Do not use your own training data or general knowledge for facts. If the search results contain the answer, summarize it accurately.\n"
        f"2. **Handle Conflicts**: If there are conflicting facts in the search results, present the most recent and reliable source (e.g. incumbent status or dates).\n"
        f"3. **Direct Output**: Do NOT use preambles like 'Based on the search results...' or 'Here is the answer'. Start your answer immediately and naturally.\n"
        f"4. **Citations**: Always list the URLs or titles of the sources you used from the SEARCH RESULTS at the very end of your response.\n\n"
        f"Deliver a professional response that directly answers the user query using only the provided search results.\n"
        f"{Baymax.HERO_AI_UNIVERSE}"
    )

    import os
    groq_keys = []
    if groq_key:
        groq_keys.append(groq_key.strip("'\" "))
    
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
            logger.info(f"[web_search] Attempting Groq summarization with key index {i}")
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {gk}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 1024,
                    "temperature": 0.4
                },
                timeout=15,
            )
            if r.status_code == 200:
                text = r.json().get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                if text:
                    logger.info(f"[web_search] Groq summarization successful with key index {i}")
                    return text
            else:
                logger.error(f"[web_search] Groq summarization key index {i} failed: {r.status_code}")
        except Exception as e:
            logger.error(f"[web_search] Groq summarization error with key index {i}: {e}")

    return None

def _plain_summary(query: str, ddg_results: list[dict], wiki_summary: str) -> str:
    """Fallback plain-text answer when Gemini and Groq are unavailable."""
    parts = [f"Here is what I found for: {query}\n"]
    if wiki_summary:
        parts.append(f"Wikipedia:\n{wiki_summary}\n")
    for r in ddg_results[:3]:
        parts.append(f"• {r['title']}\n  {r['snippet']}\n  {r['url']}")
    return "\n".join(parts) if len(parts) > 1 else "No results found."

def perform_web_search(
    query: str,
    gemini_key: str = "",
    chat_history: list = None,
    groq_key: str = "",
) -> tuple:
    """
    Search DuckDuckGo + Wikipedia, then summarise with Gemini or Groq.
    Returns (answer, rewritten_query). If search is not needed, answer is None.
    """
    need_live_data = True
    rewritten_query = query
    
    try:
        log_query = query.split('\n')[0]
        if len(log_query) > 100:
            log_query = log_query[:100] + "..."
        logger.info(f"[web_search] Analyzing and rewriting query: {log_query!r}")
        need_live_data, rewritten_query = rewrite_query_for_search(
            query=query, 
            chat_history=chat_history, 
            gemini_key=gemini_key,
            groq_key=groq_key
        )
    except Exception as e:
        logger.error(f"[web_search] Query analysis/rewrite failed: {e}")
        need_live_data = True
        rewritten_query = query

    if not need_live_data:
        logger.info(f"[web_search] Query does not require live data. Bypassing search task.")
        return None, rewritten_query

    logger.info(f"[web_search] Query requires live data. Executing search for: {rewritten_query!r}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_ddg = executor.submit(_search_duckduckgo, rewritten_query, 5)
        future_wiki = executor.submit(_search_wikipedia, rewritten_query, 5)
        
        try:
            ddg_results = future_ddg.result()
        except Exception as e:
            logger.error("[web_search] Concurrent DDG search failed: %s", e)
            ddg_results = []
            
        try:
            wiki_summary = future_wiki.result()
        except Exception as e:
            logger.error("[web_search] Concurrent Wiki search failed: %s", e)
            wiki_summary = ""

    answer = None
    if gemini_key:
        try:
            answer = _summarise_with_gemini(rewritten_query, ddg_results, wiki_summary, gemini_key)
        except Exception as e:
            logger.error(f"[web_search] Gemini summarization failed: {e}")
            answer = None

    if not answer:
        try:
            answer = _summarise_with_groq(rewritten_query, ddg_results, wiki_summary, groq_key)
        except Exception as e:
            logger.error(f"[web_search] Groq summarization fallback failed: {e}")
            answer = None

    if not answer:
        answer = _plain_summary(rewritten_query, ddg_results, wiki_summary)
    
    return answer, rewritten_query