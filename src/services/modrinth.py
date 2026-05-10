# modrinth.py
# A lightweight client for the Modrinth API, focused on hash-based mod resolution for modpacks.
# Under the MIT License.

import asyncio
import time
import aiohttp
from typing import Optional
import os

username = os.environ.get('USERNAME') or os.environ.get('USER') or "unknown_user"

BASE_URL        = "https://api.modrinth.com/v2"
USER_AGENT      = f"StormCode/Nexa/{username}"
_RATE_LIMIT     = 200           # Target requests per minute
_MIN_INTERVAL   = 60 / _RATE_LIMIT  # 0.3s between requests

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    def __init__(self, interval: float):
        self._interval  = interval
        self._lock      = asyncio.Lock()
        self._last_call = 0.0

    async def acquire(self):
        async with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last_call
            wait    = self._interval - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

_limiter = _RateLimiter(_MIN_INTERVAL)


# ---------------------------------------------------------------------------
# Internal request helper
# ---------------------------------------------------------------------------

def _headers() -> dict:
    return {"User-Agent": USER_AGENT}


async def _get(path: str) -> Optional[dict]:
    """
    Rate-limited GET against the Modrinth API.
    Returns parsed JSON on success, None on 404, raises on other errors.
    """
    await _limiter.acquire()
    async with aiohttp.ClientSession(headers=_headers()) as session:
        async with session.get(f"{BASE_URL}{path}") as response:
            if response.status == 404:
                return None
            response.raise_for_status()
            return await response.json()


# ---------------------------------------------------------------------------
# Hash operations
# ---------------------------------------------------------------------------

async def get_version_from_hash(hash: str, algorithm: str = "sha512") -> Optional[dict]:
    """
    Look up a version object from a file hash.
    Returns the full version dict, or None if not found.

    The returned dict includes:
        - id, project_id, name, version_number
        - game_versions: list[str]
        - loaders: list[str]
        - files: list of file objects, each with 'url', 'filename', 'hashes'
    """
    return await _get(f"/version_file/{hash}?algorithm={algorithm}")


async def verify_hash(hash: str, algorithm: str = "sha512") -> bool:
    """
    Verify that a file hash exists and is known to Modrinth.
    Returns True if found, False if not.
    """
    return await get_version_from_hash(hash, algorithm) is not None


# ---------------------------------------------------------------------------
# Download resolution
# ---------------------------------------------------------------------------

async def get_download_url(
    hash: str,
    game_version: str,
    loader: str,
    algorithm: str = "sha512"
) -> Optional[str]:
    """
    Given a file hash, resolve the download URL for a specific
    game version and loader combination.

    Returns None if the hash isn't found or the version doesn't
    match the requested game_version/loader.
    """
    version = await get_version_from_hash(hash, algorithm)
    if version is None:
        return None

    if game_version not in version.get("game_versions", []):
        return None
    if loader.lower() not in [l.lower() for l in version.get("loaders", [])]:
        return None

    files = version.get("files", [])
    if not files:
        return None

    for file in files:
        if file.get("primary", False):
            return file["url"]

    return files[0]["url"]


async def search_by_hash(
    hash: str,
    game_version: str,
    loader: str,
    algorithm: str = "sha512"
) -> Optional[dict]:
    """
    Search for a mod by hash and return a summary dict if it matches
    the requested game version and loader. Useful for modpack validation.

    Returns:
        {
            "project_id":     str,
            "version_id":     str,
            "version_number": str,
            "name":           str,
            "game_versions":  list[str],
            "loaders":        list[str],
            "download_url":   str,
            "filename":       str,
        }
        or None if not found / doesn't match.
    """
    version = await get_version_from_hash(hash, algorithm)
    if version is None:
        return None

    if game_version not in version.get("game_versions", []):
        return None
    if loader.lower() not in [l.lower() for l in version.get("loaders", [])]:
        return None

    files   = version.get("files", [])
    primary = next((f for f in files if f.get("primary", False)), files[0] if files else None)
    if primary is None:
        return None

    return {
        "project_id":     version["project_id"],
        "version_id":     version["id"],
        "version_number": version["version_number"],
        "name":           version["name"],
        "game_versions":  version["game_versions"],
        "loaders":        version["loaders"],
        "download_url":   primary["url"],
        "filename":       primary["filename"],
    }

# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------

async def get_project(project_id: str) -> Optional[dict]:
    """
    Fetch a project's metadata by ID or slug.
    Returns the full project dict, or None if not found.

    Relevant fields for side-filtering:
        - client_side: "required" | "optional" | "unsupported" | "unknown"
        - server_side: "required" | "optional" | "unsupported" | "unknown"
    """
    return await _get(f"/project/{project_id}")


def is_client_only(project: dict) -> bool:
    """
    Returns True if a project should be excluded from a server install.
    A mod is client-only when the server explicitly doesn't support it:
        server_side == "unsupported"
    """
    return project.get("server_side") == "unsupported"