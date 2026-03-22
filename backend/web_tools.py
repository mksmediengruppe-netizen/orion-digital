"""
Web Tools — ORION Digital v1.0 Web Search & Live Data
====================================================
Модуль для поиска в интернете и получения данных с веб-страниц.

Tools:
- web_search: Search via DuckDuckGo/Brave/Tavily with ranked results
- web_fetch: Fetch and parse web pages to clean markdown
- needs_search: Classifier to detect if query needs current data
"""

import os
import re
import json
import time
import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from urllib.parse import quote_plus, urlparse

logger = logging.getLogger("web_tools")

# Cache for search results (avoid duplicate searches)
_search_cache = {}
_CACHE_TTL = 300  # 5 minutes


def web_search(query: str, num_results: int = 8, search_type: str = "general") -> Dict[str, Any]:
    """
    Search the web using multiple providers with fallback.
    
    Providers (in order): DuckDuckGo, Brave Search API, Google Custom Search
    Returns ranked results with title, snippet, URL, and source.
    """
    cache_key = hashlib.md5(f"{query}:{num_results}:{search_type}".encode()).hexdigest()
    
    # Check cache
    if cache_key in _search_cache:
        cached = _search_cache[cache_key]
        if time.time() - cached["timestamp"] < _CACHE_TTL:
            return cached["data"]

    results = []
    source = "none"

    # Provider 1: DuckDuckGo (no API key needed)
    try:
        results = _search_duckduckgo(query, num_results)
        source = "duckduckgo"
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed: {e}")

    # Provider 2: Brave Search API (if available)
    if not results:
        brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
        if brave_key:
            try:
                results = _search_brave(query, num_results, brave_key)
                source = "brave"
            except Exception as e:
                logger.warning(f"Brave search failed: {e}")

    # Provider 3: Tavily (if available)
    if not results:
        tavily_key = os.environ.get("TAVILY_API_KEY", "")
        if tavily_key:
            try:
                results = _search_tavily(query, num_results, tavily_key)
                source = "tavily"
            except Exception as e:
                logger.warning(f"Tavily search failed: {e}")

    if not results:
        return {"success": False, "error": "All search providers failed", "results": []}

    response = {
        "success": True,
        "query": query,
        "source": source,
        "count": len(results),
        "results": results[:num_results],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    # Cache results
    _search_cache[cache_key] = {"data": response, "timestamp": time.time()}

    return response


def _search_duckduckgo(query: str, num_results: int) -> List[Dict]:
    """Search using DuckDuckGo HTML scraping."""
    import requests as req

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # Use DuckDuckGo lite
    resp = req.get(
        f"https://lite.duckduckgo.com/lite/",
        params={"q": query, "kl": "ru-ru"},
        headers=headers,
        timeout=15
    )

    results = []
    if resp.status_code == 200:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Parse results from DuckDuckGo lite
        links = soup.find_all('a', class_='result-link') or soup.find_all('a', href=True)
        snippets = soup.find_all('td', class_='result-snippet') or soup.find_all('span', class_='link-text')

        seen_urls = set()
        for link in links:
            href = link.get('href', '')
            title = link.get_text(strip=True)

            if not href or not title or href.startswith('/') or 'duckduckgo.com' in href:
                continue
            if href in seen_urls:
                continue
            seen_urls.add(href)

            # Try to find corresponding snippet
            snippet = ""
            parent = link.find_parent('tr')
            if parent:
                snippet_td = parent.find_next_sibling('tr')
                if snippet_td:
                    snippet = snippet_td.get_text(strip=True)[:300]

            results.append({
                "title": title[:200],
                "url": href,
                "snippet": snippet,
                "source": "duckduckgo"
            })

            if len(results) >= num_results:
                break

    # Fallback: DuckDuckGo API (instant answers)
    if not results:
        resp2 = req.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers=headers,
            timeout=10
        )
        if resp2.status_code == 200:
            data = resp2.json()
            # Related topics
            for topic in data.get("RelatedTopics", [])[:num_results]:
                if isinstance(topic, dict) and "FirstURL" in topic:
                    results.append({
                        "title": topic.get("Text", "")[:200],
                        "url": topic["FirstURL"],
                        "snippet": topic.get("Text", "")[:300],
                        "source": "duckduckgo_api"
                    })

    return results


def _search_brave(query: str, num_results: int, api_key: str) -> List[Dict]:
    """Search using Brave Search API."""
    import requests as req

    resp = req.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": num_results},
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key
        },
        timeout=15
    )

    results = []
    if resp.status_code == 200:
        data = resp.json()
        for item in data.get("web", {}).get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("description", "")[:300],
                "source": "brave"
            })

    return results


def _search_tavily(query: str, num_results: int, api_key: str) -> List[Dict]:
    """Search using Tavily API."""
    import requests as req

    resp = req.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": num_results,
            "search_depth": "basic"
        },
        timeout=15
    )

    results = []
    if resp.status_code == 200:
        data = resp.json()
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", "")[:300],
                "source": "tavily"
            })

    return results


def web_fetch(url: str, max_length: int = 15000) -> Dict[str, Any]:
    """
    Fetch and parse a web page to clean text/markdown.
    Uses trafilatura for content extraction with BeautifulSoup fallback.
    """
    import requests as req

    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    try:
        resp = req.get(url, headers=headers, timeout=20, allow_redirects=True)
        resp.raise_for_status()

        content_type = resp.headers.get('content-type', '')
        if 'text/html' not in content_type and 'application/xhtml' not in content_type:
            return {
                "success": False,
                "error": f"Not an HTML page (content-type: {content_type})",
                "url": url
            }

        html = resp.text

        # Try trafilatura first
        text = None
        try:
            import trafilatura
            text = trafilatura.extract(html, include_links=True, include_tables=True,
                                       include_formatting=True, output_format='txt')
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"Trafilatura extraction failed: {e}")

        # Fallback to BeautifulSoup
        if not text:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')

            # Remove script, style, nav, footer
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'noscript']):
                tag.decompose()

            # Get title
            title = soup.title.string if soup.title else ""

            # Get main content
            main = soup.find('main') or soup.find('article') or soup.find('div', {'role': 'main'}) or soup.body
            if main:
                text = main.get_text(separator='\n', strip=True)
            else:
                text = soup.get_text(separator='\n', strip=True)

            # Clean up
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            text = '\n'.join(lines)

        if text and len(text) > max_length:
            text = text[:max_length] + f"\n\n... [обрезано, всего {len(text)} символов]"

        # Extract metadata
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        title = soup.title.string if soup.title else urlparse(url).netloc
        description = ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            description = meta_desc.get('content', '')

        return {
            "success": True,
            "url": url,
            "title": title,
            "description": description[:300],
            "content": text or "Не удалось извлечь текст со страницы",
            "length": len(text) if text else 0,
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        return {
            "success": False,
            "url": url,
            "error": f"Failed to fetch page: {str(e)}"
        }


def needs_search(query: str) -> bool:
    """
    Classify whether a query needs web search for current data.
    Returns True if search is needed, False if answerable from training data.
    """
    # Keywords indicating need for current data
    current_data_keywords = [
        "сегодня", "вчера", "сейчас", "текущ", "последн", "новост", "цена",
        "курс", "погода", "расписание", "актуальн", "свежи", "2025", "2026",
        "today", "yesterday", "current", "latest", "news", "price", "weather",
        "stock", "schedule", "recent", "update", "live", "real-time",
        "что произошло", "what happened", "who won", "кто выиграл",
        "найди", "search", "поищи", "загугли", "google"
    ]

    query_lower = query.lower()

    # Check for current data keywords
    if any(kw in query_lower for kw in current_data_keywords):
        return True

    # Check for questions about specific entities that might need current info
    question_patterns = [
        r"как\s+дела\s+у",
        r"что\s+нового\s+в",
        r"какой\s+курс",
        r"сколько\s+стоит",
        r"where\s+is",
        r"how\s+much\s+is",
        r"what\s+is\s+the\s+(current|latest|price)",
    ]

    for pattern in question_patterns:
        if re.search(pattern, query_lower):
            return True

    # Simple questions don't need search
    simple_patterns = [
        r"^(привет|hello|hi|здравствуй)",
        r"^(что такое|what is)\s+\w+$",
        r"^(как|how)\s+(написать|сделать|создать|write|make|create)",
        r"^(напиши|write|create|сделай|generate)",
        r"(код|code|функци|class|html|css|python)",
    ]

    for pattern in simple_patterns:
        if re.search(pattern, query_lower):
            return False

    return False


def format_search_results_for_llm(results: Dict[str, Any]) -> str:
    """Format search results as context for LLM with citations."""
    if not results.get("success") or not results.get("results"):
        return ""

    formatted = "## Результаты поиска в интернете\n\n"
    for i, r in enumerate(results["results"], 1):
        formatted += f"**[{i}] {r['title']}**\n"
        formatted += f"URL: {r['url']}\n"
        if r.get('snippet'):
            formatted += f"{r['snippet']}\n"
        formatted += "\n"

    formatted += "\n*Используй номера источников [1], [2], ... для цитирования в ответе.*\n"
    return formatted


def clear_search_cache():
    """Clear the search cache."""
    global _search_cache
    _search_cache = {}


# ══════════════════════════════════════════════════════════════
# OOP WRAPPERS (for compatibility with spec)
# ══════════════════════════════════════════════════════════════

class WebSearcher:
    """OOP wrapper around web_search function."""

    def __init__(self, default_engine: str = "duckduckgo"):
        self.default_engine = default_engine

    def search(self, query: str, num_results: int = 8, search_type: str = "general") -> Dict[str, Any]:
        return web_search(query, num_results, search_type)

    def needs_search(self, query: str) -> bool:
        return needs_search(query)


class WebFetcher:
    """OOP wrapper around web_fetch function."""

    def __init__(self, max_length: int = 15000):
        self.max_length = max_length

    def fetch(self, url: str, max_length: int = None) -> Dict[str, Any]:
        return web_fetch(url, max_length or self.max_length)
