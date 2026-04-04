# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reddit (OAuth2 installed client)

Drop-in replacement for the default reddit engine that obtains OAuth2
tokens using the installed-client grant (same technique as Redlib's
GenericWebAuth). No API registration or secrets required.

Authenticated requests get 100 req/min vs 10 req/min unauthenticated.
"""

import json
import logging
import typing as t
from datetime import datetime
from urllib.parse import urlencode, urljoin, urlparse

try:
    from searx.enginelib import EngineCache
    from searx.network import post as http_post
except ImportError:
    # Standalone mode: stub SearXNG dependencies with stdlib equivalents
    import urllib.request

    class EngineCache:  # type: ignore[no-redef]
        def __init__(self, _name: str) -> None:
            self._store: dict[str, str] = {}

        def get(self, key: str) -> t.Optional[str]:
            return self._store.get(key)

        def set(self, key: str, value: str, expire: int = 0) -> None:
            self._store[key] = value

    class _StandaloneResponse:
        def __init__(self, resp: "urllib.request.http.client.HTTPResponse") -> None:
            self.status_code = resp.status
            self._body = resp.read()
            self.text = self._body.decode()

        def json(self) -> dict:
            return json.loads(self.text)

    def http_post(
        url: str, data: t.Any = None, headers: t.Optional[dict] = None, timeout: int = 5
    ) -> _StandaloneResponse:  # type: ignore[misc]
        encoded = urlencode(data).encode() if isinstance(data, dict) else data
        req = urllib.request.Request(
            url, data=encoded, headers=headers or {}, method="POST"
        )
        return _StandaloneResponse(urllib.request.urlopen(req, timeout=timeout))


logger = logging.getLogger(__name__)

about = {
    "website": "https://www.reddit.com/",
    "wikidata_id": "Q1136",
    "official_api_documentation": "https://www.reddit.com/dev/api",
    "use_official_api": True,
    "require_api_key": False,
    "results": "JSON",
}

categories = ["social media"]
page_size = 25

# Installed-client OAuth ID (configurable via settings.yml, defaults to
# Redlib's GenericWebAuth client ID as fallback)
reddit_client_id = "M1hmQkpXbGlIdnFBQ25YcmZJWWxMdzo"
_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_OAUTH_URL = "https://oauth.reddit.com/"
_TOKEN_EXPIRY = 3500  # tokens last 3600s; refresh slightly early

CACHE: t.Optional["EngineCache"] = None


def _random_device_id() -> str:
    """Generate a random 20-char alphanumeric device ID."""
    import random
    import string

    return "".join(random.choices(string.ascii_letters + string.digits, k=20))


def setup(engine_settings: dict[str, t.Any]) -> bool:
    global CACHE  # pylint: disable=global-statement
    CACHE = EngineCache(engine_settings["name"])
    logger.info("Reddit OAuth2 (installed client) engine initialized")
    return True


def _authenticate() -> tuple[str, int]:
    """Obtain a bearer token via installed-client grant."""
    from base64 import b64encode

    device_id = _random_device_id()
    auth = b64encode(f"{reddit_client_id}:".encode()).decode()
    resp = http_post(
        _TOKEN_URL,
        data={
            "grant_type": "https://oauth.reddit.com/grants/installed_client",
            "device_id": device_id,
        },
        headers={
            "Authorization": f"Basic {auth}",
            "User-Agent": "Mozilla/5.0 (compatible; SearXNG)",
        },
        timeout=5,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Reddit OAuth2 failed (status {resp.status_code}): {resp.text}"
        )
    data = resp.json()
    return data["access_token"], data.get("expires_in", 3600)


def _get_token() -> str:
    """Return a cached token or fetch a new one."""
    key = "reddit_installed_client"
    token: t.Optional[str] = CACHE.get(key)  # type: ignore[union-attr]
    if token:
        return token
    token, expires_in = _authenticate()
    CACHE.set(key=key, value=token, expire=min(expires_in - 100, _TOKEN_EXPIRY))  # type: ignore[union-attr]
    logger.info("Reddit OAuth2 token acquired (expires in %ds)", expires_in)
    return token


def request(query, params):
    token = _get_token()
    args = urlencode({"q": query, "limit": page_size, "type": "link"})
    params["url"] = f"{_OAUTH_URL}search?{args}"
    params["headers"]["Authorization"] = f"Bearer {token}"
    params["headers"]["User-Agent"] = "Mozilla/5.0 (compatible; SearXNG)"
    return params


def response(resp):
    img_results = []
    text_results = []

    search_results = json.loads(resp.text)

    if "data" not in search_results:
        return []

    posts = search_results.get("data", {}).get("children", [])

    for post in posts:
        data = post["data"]
        params = {
            "url": urljoin("https://www.reddit.com/", data["permalink"]),
            "title": data["title"],
        }

        thumbnail = data.get("thumbnail", "")
        url_info = urlparse(thumbnail)
        if url_info[1] != "" and url_info[2] != "":
            params["img_src"] = data["url"]
            params["thumbnail_src"] = thumbnail
            params["template"] = "images.html"
            img_results.append(params)
        else:
            created = datetime.fromtimestamp(data["created_utc"])
            content = data.get("selftext", "")
            if len(content) > 500:
                content = content[:500] + "..."
            params["content"] = content
            params["publishedDate"] = created
            text_results.append(params)

    return img_results + text_results


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Test Reddit OAuth2 engine standalone")
    parser.add_argument(
        "query", nargs="?", default="python asyncio", help="Search query"
    )
    parser.add_argument("--client-id", default=None, help="Reddit OAuth client ID")
    args = parser.parse_args()

    if args.client_id:
        reddit_client_id = args.client_id

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Initialize cache
    setup({"name": "reddit-test"})

    # Build request
    params: dict[str, t.Any] = {"headers": {}}
    request(args.query, params)
    logger.info("URL: %s", params["url"])

    # Execute search using stdlib
    req = urllib.request.Request(params["url"], headers=params["headers"])
    raw = urllib.request.urlopen(req, timeout=10)

    # Parse response
    resp_obj = _StandaloneResponse(raw)
    logger.info("Status: %d, Body length: %d", resp_obj.status_code, len(resp_obj.text))

    results = response(resp_obj)
    if not results:
        logger.warning("No results returned")
        sys.exit(1)

    for i, r in enumerate(results[:10], 1):
        print(f"\n[{i}] {r['title']}")
        print(f"    {r['url']}")
        if "content" in r and r["content"]:
            print(f"    {r['content'][:120]}")
