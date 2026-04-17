import json
import re
import sqlite3
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from platform import system
from urllib.parse import parse_qs, urlparse

import httpx

from ..config import (
    ENGINE_API_BASE,
    ENGINE_API_TOKEN,
    ENGINE_DB_PATH,
    ENGINE_SETTINGS_PATH,
    ENGINE_VOLUME_PATH,
    DOWNLOADED_IDS_CACHE_SECONDS,
)
from ..db import update_sqlite_creator_sec_user_id


DOUYIN_USER_PATTERN = re.compile(r"/user/([^/?]+)")
TIKTOK_SECUID_PATTERN = re.compile(r"[?&]secUid=([^&]+)")
SETTINGS_ENCODING = "utf-8-sig" if system() == "Windows" else "utf-8"

ENGINE_CONFIG_DEFAULTS = {
    "desc_length": 64,
    "name_length": 128,
    "date_format": "%Y-%m-%d %H:%M:%S",
    "split": "-",
    "truncate": 50,
    "storage_format": "",
    "cookie": "",
    "cookie_tiktok": "",
    "proxy": "",
    "proxy_tiktok": "",
    "twc_tiktok": "",
    "download": True,
    "max_size": 0,
    "chunk": 1024 * 1024 * 2,
    "timeout": 10,
    "max_retry": 5,
    "max_pages": 0,
    "run_command": "",
    "ffmpeg": "",
    "live_qualities": "",
    "douyin_platform": True,
    "tiktok_platform": True,
    "browser_info": {
        "User-Agent": "",
        "pc_libra_divert": "Windows",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "",
        "engine_name": "Blink",
        "engine_version": "",
        "os_name": "Windows",
        "os_version": "10",
        "webid": "",
    },
    "browser_info_tiktok": {
        "User-Agent": "",
        "app_language": "zh-Hans",
        "browser_language": "zh-CN",
        "browser_name": "Mozilla",
        "browser_platform": "Win32",
        "browser_version": "",
        "language": "zh-Hans",
        "os": "windows",
        "priority_region": "US",
        "region": "US",
        "tz_name": "Asia/Shanghai",
        "webcast_language": "zh-Hans",
        "device_id": "",
    },
}

_DOWNLOADED_IDS_CACHE: set[str] | None = None
_DOWNLOADED_IDS_CACHE_EXPIRES_AT: datetime | None = None


def normalize_download_root(root: str) -> str:
    value = str(root or "").strip()
    if not value:
        return ""
    normalized = value.replace("\\", "/")
    if normalized in {"/Volume", "Volume"}:
        return str(ENGINE_VOLUME_PATH)
    for prefix in ("/Volume/", "Volume/"):
        if normalized.startswith(prefix):
            relative = normalized[len(prefix):].strip("/")
            return str(ENGINE_VOLUME_PATH.joinpath(*relative.split("/"))) if relative else str(ENGINE_VOLUME_PATH)
    return value


def read_downloaded_ids(force_refresh: bool = False) -> set[str]:
    global _DOWNLOADED_IDS_CACHE, _DOWNLOADED_IDS_CACHE_EXPIRES_AT
    now = datetime.now()
    if (
        not force_refresh
        and _DOWNLOADED_IDS_CACHE is not None
        and _DOWNLOADED_IDS_CACHE_EXPIRES_AT is not None
        and _DOWNLOADED_IDS_CACHE_EXPIRES_AT > now
    ):
        return set(_DOWNLOADED_IDS_CACHE)
    if not ENGINE_DB_PATH.exists():
        return set()
    with sqlite3.connect(ENGINE_DB_PATH) as conn:
        rows = conn.execute("SELECT ID FROM download_data").fetchall()
    downloaded_ids = {row[0] for row in rows if row and row[0]}
    _DOWNLOADED_IDS_CACHE = downloaded_ids
    _DOWNLOADED_IDS_CACHE_EXPIRES_AT = now + timedelta(seconds=DOWNLOADED_IDS_CACHE_SECONDS)
    return set(downloaded_ids)


def invalidate_downloaded_ids_cache() -> None:
    global _DOWNLOADED_IDS_CACHE, _DOWNLOADED_IDS_CACHE_EXPIRES_AT
    _DOWNLOADED_IDS_CACHE = None
    _DOWNLOADED_IDS_CACHE_EXPIRES_AT = None


def delete_downloaded_ids(ids: list[str] | tuple[str, ...] | set[str]) -> int:
    values = [str(item).strip() for item in (ids or []) if str(item).strip()]
    if not values or not ENGINE_DB_PATH.exists():
        return 0
    with sqlite3.connect(ENGINE_DB_PATH) as conn:
        cursor = conn.executemany(
            "DELETE FROM download_data WHERE ID = ?",
            [(item,) for item in values],
        )
        conn.commit()
    invalidate_downloaded_ids_cache()
    return int(cursor.rowcount or 0)


def read_engine_settings() -> dict:
    if not ENGINE_SETTINGS_PATH.exists():
        return {}
    return json.loads(ENGINE_SETTINGS_PATH.read_text(encoding=SETTINGS_ENCODING))


def read_engine_config() -> dict:
    settings = read_engine_settings()
    data = deepcopy(ENGINE_CONFIG_DEFAULTS)
    for key, default in ENGINE_CONFIG_DEFAULTS.items():
        value = settings.get(key, deepcopy(default))
        if key in {"cookie", "cookie_tiktok"} and isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False, indent=2)
        if key in {"browser_info", "browser_info_tiktok"} and not isinstance(value, dict):
            value = deepcopy(default)
        data[key] = value
    return data


def update_engine_config(payload: dict) -> Path:
    settings = read_engine_settings()
    for key in ENGINE_CONFIG_DEFAULTS:
        if key in payload:
            settings[key] = payload[key]
    return save_engine_settings(settings)


def build_settings_payload(profile: dict, creators: list[dict]) -> dict:
    douyin = []
    tiktok = []
    for creator in creators:
        item = {
            "mark": creator["mark"],
            "url": creator["url"],
            "tab": creator["tab"],
            "earliest": "",
            "latest": "",
            "enable": bool(creator["enabled"]),
        }
        if creator["platform"] == "tiktok":
            tiktok.append(item)
        else:
            douyin.append(item)
    return {
        "accounts_urls": douyin,
        "accounts_urls_tiktok": tiktok,
        "root": normalize_download_root(profile["root_path"]),
        "folder_name": profile["folder_name"],
        "name_format": profile["name_format"],
        "folder_mode": bool(profile["folder_mode"]),
        "music": bool(profile["music"]),
        "dynamic_cover": bool(profile["dynamic_cover"]),
        "static_cover": bool(profile["static_cover"]),
    }


def build_run_command(platform: str) -> str:
    return "5 12 1" if platform == "tiktok" else "5 1 1"


def save_engine_settings(data: dict) -> Path:
    ENGINE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENGINE_SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding=SETTINGS_ENCODING,
    )
    return ENGINE_SETTINGS_PATH


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    if ENGINE_API_TOKEN:
        headers["token"] = ENGINE_API_TOKEN
    return headers


def _post(path: str, payload: dict) -> dict:
    response = httpx.post(
        f"{ENGINE_API_BASE}{path}",
        json=payload,
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def expand_share_url(platform: str, text: str) -> str:
    path = "/tiktok/share" if platform == "tiktok" else "/douyin/share"
    try:
        data = _post(path, {"text": text, "proxy": ""})
        return data.get("url") or text
    except Exception:
        return text


def extract_sec_user_id(platform: str, url: str) -> str:
    if platform == "tiktok":
        if match := TIKTOK_SECUID_PATTERN.search(url):
            return match.group(1)
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        return query.get("secUid", [""])[0]
    if match := DOUYIN_USER_PATTERN.search(url):
        return match.group(1)
    return ""


def resolve_creator_identity(creator: dict) -> str:
    if creator.get("sec_user_id"):
        return creator["sec_user_id"]
    expanded = expand_share_url(creator["platform"], creator["url"])
    sec_user_id = extract_sec_user_id(creator["platform"], expanded)
    if sec_user_id:
        update_sqlite_creator_sec_user_id(creator["id"], sec_user_id)
    return sec_user_id


def fetch_account_items(creator: dict) -> list[dict]:
    sec_user_id = resolve_creator_identity(creator)
    if not sec_user_id:
        raise ValueError("Unable to resolve sec_user_id from creator url")
    path = "/tiktok/account" if creator["platform"] == "tiktok" else "/douyin/account"
    data = _post(
        path,
        {
            "sec_user_id": sec_user_id,
            "tab": creator.get("tab") or "post",
            "source": False,
        },
    )
    return data.get("data") or []
