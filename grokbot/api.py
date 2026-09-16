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


class APIRequestError(Exception):
    """Raised when an API returns an error response."""

    def __init__(self, status, message, retryable=False, retry_after=None):
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after
        super().__init__(f"HTTP {status}: {message}")


class APIRetriesExceededError(Exception):
    """Raised when API request fails after maximum retries."""


def _retry_after_seconds(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _api_error_details(body):
    try:
        error = json.loads(body).get("error", {})
        if isinstance(error, dict):
            return error.get("message") or body, error.get("code") or error.get("type")
    except (TypeError, ValueError):
        pass
    return body, None


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
        try:
            async with session.post(api_url, headers=headers, json=payload, timeout=timeout) as response:
                if response.status >= 400:
                    error_body = (await response.text()).strip()[:1000]
                    error_message, error_code = _api_error_details(error_body)
                    retryable = (
                        (response.status == 429 and error_code != "insufficient_quota")
                        or 500 <= response.status < 600
                    )
                    raise APIRequestError(
                        response.status,
                        error_message,
                        retryable=retryable,
                        retry_after=_retry_after_seconds(response.headers.get("Retry-After")),
                    )
                response_data = await response.json()
                if cacheable:
                    api_cache[cache_key] = response_data
                    logging.info(f"Cached API response for key: {cache_key}")
                return response_data
        except APIRequestError as e:
            if e.retryable and attempt < retries - 1:
                delay = e.retry_after if e.retry_after is not None else 2 ** attempt
                logging.warning(
                    f"API request returned HTTP {e.status}; retrying in {delay:.1f}s "
                    f"(attempt {attempt + 1}/{retries})"
                )
                await asyncio.sleep(delay)
                continue
            logging.error(f"API error: HTTP {e.status}: {e}")
            raise
        except aiohttp.ClientResponseError as e:
            logging.error(f"API error: HTTP {e.status}: {e.message}")
            raise
        except (aiohttp.ClientConnectionError, asyncio.TimeoutError) as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
            else:
                logging.error(f"Connection error: {str(e)}")
                raise
    raise APIRetriesExceededError("Failed to get response after retries")