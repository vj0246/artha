"""HTTP access to NSE archive hosts.

NSE endpoints are scrape-hostile: requests need browser-like headers, and
failures must be loud, never silently skipped (plan section 5.1). 404 is a
distinct outcome because it is expected on non-trading days; everything else
retries with exponential backoff and then raises.
"""

import time

import httpx

POLITE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nseindia.com/",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TIMEOUT_S = 30.0


class NseNotFoundError(Exception):
    """The archive has no file at this URL (expected on holidays/weekends)."""

    def __init__(self, url: str) -> None:
        super().__init__(f"NSE archive 404: {url}")
        self.url = url


class NseDownloadError(Exception):
    """Download failed after retries, or the response body is not the file."""

    def __init__(self, url: str, detail: str) -> None:
        super().__init__(f"NSE download failed: {url} ({detail})")
        self.url = url
        self.detail = detail


def nse_client() -> httpx.Client:
    return httpx.Client(headers=POLITE_HEADERS, timeout=DEFAULT_TIMEOUT_S, follow_redirects=True)


def nse_api_client() -> httpx.Client:
    """Client for www.nseindia.com/api/* endpoints, which require the session
    cookies handed out by the homepage (the "cookie dance").

    The homepage request must look like a browser page load (HTML Accept
    header); the JSON Accept header goes on the API calls only.
    """
    client = httpx.Client(
        headers={**POLITE_HEADERS, "Accept": "application/json, text/plain, */*"},
        timeout=DEFAULT_TIMEOUT_S,
        follow_redirects=True,
    )
    last_detail = "no attempts made"
    for attempt in range(3):
        try:
            resp = client.get(
                "https://www.nseindia.com/",
                headers={
                    "Accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                        "image/webp,*/*;q=0.8"
                    )
                },
            )
        except httpx.HTTPError as exc:
            last_detail = f"transport error: {exc}"
        else:
            if resp.status_code == 200:
                return client
            last_detail = f"HTTP {resp.status_code}"
        time.sleep(2.0 * 2**attempt)
    client.close()
    raise NseDownloadError("https://www.nseindia.com/", f"cookie dance {last_detail}")


def fetch(url: str, *, client: httpx.Client, retries: int = 3, backoff_s: float = 2.0) -> bytes:
    """GET with retries on transient failures. Raises NseNotFoundError on 404."""
    last_detail = "no attempts made"
    for attempt in range(retries):
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            last_detail = f"transport error: {exc}"
        else:
            if resp.status_code == 200:
                return resp.content
            if resp.status_code == 404:
                raise NseNotFoundError(url)
            last_detail = f"HTTP {resp.status_code}"
        if attempt < retries - 1:
            time.sleep(backoff_s * 2**attempt)
    raise NseDownloadError(url, last_detail)
