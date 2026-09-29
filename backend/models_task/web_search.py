"""
web_search.py (FIXED)
─────────────────────────────────────────────
Searches DuckDuckGo, Wikipedia, Serpstack, and Serply.
Returns raw context for the Query Router / Final Model.

Dependencies:
    pip install ddgs wikipedia requests lxml beautifulsoup4
"""

import logging
import concurrent.futures
import trafilatura
import os
import requests

logger = logging.getLogger("hero_ai.web_search")


# ── DuckDuckGo ────────────────────────────────────────────────────────────────

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
    """Return a list of {source, title, url, snippet} dicts from DuckDuckGo."""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "source": "DuckDuckGo",
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


# ── Serpstack ─────────────────────────────────────────────────────────────────

def _search_serpstack(query: str, max_results: int = 5) -> list[dict]:
    api_key = os.getenv("Serpstack")
    if not api_key:
        logger.error("[web_search] Serpstack API key not found in env.")
        return None
        
    try:
        params = {
            'access_key': api_key,
            'query': query,
            'num': max_results
        }
        response = requests.get('http://api.serpstack.com/search', params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'error' in data:
            logger.error(f"[web_search] Serpstack returned error: {data['error']}")
            return None
            
        results = []
        for r in data.get("organic_results", [])[:max_results]:
            results.append({
                "source": "Serpstack",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
                "published_at": r.get("displayed_link", "")
            })
        return results
    except Exception as e:
        logger.error(f"[web_search] Serpstack error: {e}")
        return None


# ── Serply ─────────────────────────────────────────────────────────────────

def _search_serply(query: str, max_results: int = 5) -> list[dict]:
    api_key = os.getenv("Serply")
    if not api_key:
        logger.error("[web_search] Serply API key not found in env.")
        return []
        
    try:
        headers = {
            'X-Api-Key': api_key,
            'Content-Type': 'application/json'
        }
        url = f"https://api.serply.io/v1/search/q={requests.utils.quote(query)}"
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for r in data.get("results", [])[:max_results]:
            results.append({
                "source": "Serply",
                "title": r.get("title", ""),
                "url": r.get("link", ""),
                "snippet": r.get("snippet", "") or r.get("description", ""),
            })
        return results
    except Exception as e:
        logger.error(f"[web_search] Serply error: {e}")
        return []

def _search_serpstack_with_fallback(query: str, max_results: int = 3) -> tuple:
    results = _search_serpstack(query, max_results)
    if results is None:
        return (True, _search_serply(query, max_results))
    return (False, results)


def _clean_and_dedupe(results: list, seen_urls: set, max_length: int = 1000) -> list:
    cleaned = []
    for r in results:
        url = r.get("url", "").strip()
        if not url or url in seen_urls:
            continue
            
        snippet = r.get("snippet", "").strip()
        if not snippet:
            continue
            
        # Basic cleanup: remove extra whitespace, trim length
        snippet = " ".join(snippet.split())
        if len(snippet) > max_length:
            snippet = snippet[:max_length] + "..."
            
        seen_urls.add(url)
        r["snippet"] = snippet
        cleaned.append(r)
        
        if len(cleaned) >= 3:
            break
    return cleaned

# ── Raw Search Fetcher ───────────────────────────────────────────────────────

def perform_web_search(query: str) -> str:
    """
    Search DuckDuckGo + Wikipedia + (Serpstack -> Serply) and return the raw text context.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_ddg = executor.submit(_search_duckduckgo, query, 5)
        future_wiki = executor.submit(_search_wikipedia, query, 5)
        future_serp = executor.submit(_search_serpstack_with_fallback, query, 5)
        
        try:
            ddg_raw = future_ddg.result() or []
        except Exception:
            ddg_raw = []
            
        try:
            wiki_summary = future_wiki.result()
        except Exception:
            wiki_summary = ""

        try:
            serpstack_failed, serp_raw = future_serp.result()
            if serp_raw is None:
                serp_raw = []
        except Exception:
            serpstack_failed = True
            serp_raw = []

    # Status Logging
    wiki_status = "1 RESULTS" if wiki_summary else "NO RESULTS"
    print(f"[WebSearch] Wikipedia: {wiki_status}")
    
    ddg_status = f"{len(ddg_raw)} RESULTS" if ddg_raw else "NO RESULTS"
    print(f"[WebSearch] DuckDuckGo: {ddg_status}")
    
    if serpstack_failed:
        print("[WebSearch] Serpstack: FAILED")
        serply_status = f"{len(serp_raw)} RESULTS" if serp_raw else "NO RESULTS"
        print(f"[WebSearch] Serply: {serply_status}")
    else:
        serpstack_status = f"{len(serp_raw)} RESULTS" if serp_raw else "NO RESULTS"
        print(f"[WebSearch] Serpstack: {serpstack_status}")

    # Formatting and Cleanup
    context_parts = []
    seen_urls = set()
    
    if wiki_summary:
        wiki_title = query.title() + " - Wikipedia"
        wiki_url = f"https://en.wikipedia.org/wiki/{requests.utils.quote(query)}"
        wiki_text = f"=== Wikipedia ===\nTitle: {wiki_title}\nURL: {wiki_url}\nContent:\n{wiki_summary}"
        context_parts.append(wiki_text)
        
    ddg_cleaned = _clean_and_dedupe(ddg_raw, seen_urls)
    if ddg_cleaned:
        lines = ["=== DuckDuckGo ==="]
        for i, r in enumerate(ddg_cleaned, 1):
            source_txt = f"Result {i}\nTitle: {r.get('title', '')}\nURL: {r.get('url', '')}\nContent:\n{r.get('snippet', '')}"
            if r.get("published_at"):
                source_txt += f"\nPublished: {r.get('published_at')}"
            lines.append(source_txt)
        context_parts.append("\n\n".join(lines))
        
    serp_cleaned = _clean_and_dedupe(serp_raw, seen_urls)
    if serp_cleaned:
        provider_name = "Serply" if serpstack_failed else "Serpstack"
        lines = [f"=== {provider_name} ==="]
        for i, r in enumerate(serp_cleaned, 1):
            source_txt = f"Result {i}\nTitle: {r.get('title', '')}\nURL: {r.get('url', '')}\nContent:\n{r.get('snippet', '')}"
            if r.get("published_at"):
                source_txt += f"\nPublished: {r.get('published_at')}"
            lines.append(source_txt)
        context_parts.append("\n\n".join(lines))
        
    return "\n\n".join(context_parts)