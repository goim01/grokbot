import aiohttp
import asyncio
import logging
import json
from ddgs import DDGS

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
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=10)
            if results:
                summary = f"Here are some search results for '{query}':\n"
                for i, r in enumerate(results, 1):
                    summary += f"{i}. {r['title']}\n   {r['body']}\n\n"
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

async def send_api_request(session, api_url, headers, payload, api_timeout):
    retries = 3
    for attempt in range(retries):
        response = None
        try:
            if session.closed:
                logging.warning("Session closed, creating new aiohttp session")
                session = aiohttp.ClientSession()
            async with session.post(api_url, headers=headers, json=payload, timeout=api_timeout) as response:
                response.raise_for_status()
                return await response.json()
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