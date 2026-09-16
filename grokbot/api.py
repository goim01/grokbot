import aiohttp
import asyncio
import logging
import json
from ddgs import DDGS
from cachetools import TTLCache
import hashlib

# Cache completed API responses (max 100 entries, TTL 1 hour)
api_cache = TTLCache(maxsize=100, ttl=3600)

tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Perform a web search to get current information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    }
                },
                "required": ["query"]
            }
        }
    }
]


async def web_search(query):
    def sync_search():
        results = DDGS().text(query, max_results=10)
        if results:
            summary = f"Here are some search results for '{query}':\n"
            for i, r in enumerate(results, 1):
                title = r.get("title", "")
                body = r.get("body", "")
                summary += f"{i}. {title}\n   {body}\n\n"
            return summary.strip()
        else:
            return f"No results found for '{query}'"
    try:
        return await asyncio.to_thread(sync_search)
    except Exception as e:
        return f"Error performing search for '{query}': {str(e)}"


tools_map = {
    "web_search": web_search
}


class APIRetriesExceededError(Exception):
    """Raised when API request fails after maximum retries."""


def _payload_is_cacheable(payload):
    # Do not cache tool-calling rounds; later iterations change the message list
    # and a cached mid-loop response would break the tool loop.
    if payload.get("tools"):
        return False
    messages = payload.get("messages") or []
    for msg in messages:
        if msg.get("role") == "tool" or msg.get("tool_calls"):
            return False
    return True


async def send_api_request(session, api_url, headers, payload, api_timeout):
    cacheable = _payload_is_cacheable(payload)
    cache_key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    # Check cache
    if cacheable and cache_key in api_cache:
        logging.info(f"Cache hit for API request: {cache_key}")
        return api_cache[cache_key]

    if session is None or session.closed:
        raise RuntimeError("aiohttp session is not available")

    timeout = aiohttp.ClientTimeout(total=api_timeout)
    retries = 3
    for attempt in range(retries):
        response = None
        try:
            async with session.post(api_url, headers=headers, json=payload, timeout=timeout) as response:
                response.raise_for_status()
                response_data = await response.json()
                if cacheable:
                    api_cache[cache_key] = response_data
                    logging.info(f"Cached API response for key: {cache_key}")
                return response_data
        except aiohttp.ClientResponseError as e:
            if e.status == 429 and attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                error_body = ""
                if response is not None:
                    try:
                        error_body = await response.text()
                        error_body = error_body[:500]
                    except Exception:
                        error_body = "<unable to read response body>"
                logging.error(f"API error: HTTP {e.status}: {error_body}")
                raise
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                logging.error(f"Connection error: {str(e)}")
                raise
    raise APIRetriesExceededError("Failed to get response after retries")