from datetime import datetime, timedelta

from fastapi import HTTPException

from ..db import (
    delete_sqlite_creator,
    get_sqlite_dashboard_summary,
    get_sqlite_creator,
    list_due_sqlite_creators,
    list_sqlite_creator_options,
    list_sqlite_scan_cache,
    list_sqlite_creator_summaries_paginated,
    list_sqlite_creator_summaries,
    list_sqlite_creators,
    now_iso,
    save_sqlite_creator,
)
from ..schemas import CreatorCreate, CreatorUpdate
from .engine import delete_downloaded_ids, fetch_account_items


def _normalize_schedule_fields(item: dict) -> None:
    interval = max(0, int(item.get("auto_download_interval_minutes") or 0))
    item["auto_download_interval_minutes"] = interval
    enabled = bool(item.get("auto_download_enabled")) and interval > 0 and bool(item.get("enabled", True))
    item["auto_download_enabled"] = enabled

    start_at = item.get("auto_download_start_at")
    if hasattr(start_at, "isoformat"):
        start_at = start_at.isoformat(timespec="seconds")
    item["auto_download_start_at"] = start_at

    last_run_at = item.get("auto_download_last_run_at")
    if hasattr(last_run_at, "isoformat"):
        last_run_at = last_run_at.isoformat(timespec="seconds")
    item["auto_download_last_run_at"] = last_run_at
    item["auto_download_history"] = list(item.get("auto_download_history") or [])

    next_run_at = item.get("auto_download_next_run_at")
    if hasattr(next_run_at, "isoformat"):
        next_run_at = next_run_at.isoformat(timespec="seconds")

    if enabled:
        if next_run_at:
            item["auto_download_next_run_at"] = next_run_at
            return
        base = datetime.fromisoformat(start_at) if start_at else (datetime.now() + timedelta(minutes=interval))
        if base < datetime.now():
            base = datetime.now() + timedelta(minutes=interval)
        item["auto_download_next_run_at"] = base.isoformat(timespec="seconds")
        return

    item["auto_download_next_run_at"] = None


def _resolve_next_run_at(item: dict) -> str | None:
    interval = max(0, int(item.get("auto_download_interval_minutes") or 0))
    enabled = bool(item.get("auto_download_enabled")) and interval > 0 and bool(item.get("enabled", True))
    if not enabled:
        return None

    start_at = item.get("auto_download_start_at")
    if start_at:
        try:
            base = datetime.fromisoformat(str(start_at))
        except ValueError:
            base = datetime.now()
    else:
        base = datetime.now() + timedelta(minutes=interval)

    if base < datetime.now():
        base = datetime.now() + timedelta(minutes=interval)
    return base.isoformat(timespec="seconds")


def update_auto_download_result(
    creator_id: int,
    *,
    status: str,
    message: str,
    next_run_at: datetime | str | None = None,
    mark_run: bool = True,
):
    item = get_sqlite_creator(creator_id)
    if not item:
        raise HTTPException(status_code=404, detail="Creator not found")
    if mark_run:
        item["auto_download_last_run_at"] = now_iso()
    item["auto_download_last_status"] = status
    item["auto_download_last_message"] = message
    history = list(item.get("auto_download_history") or [])
    history.insert(0, {
        "run_at": item["auto_download_last_run_at"] if mark_run else now_iso(),
        "status": status,
        "message": message,
        "next_run_at": next_run_at.isoformat(timespec="seconds") if hasattr(next_run_at, "isoformat") else (str(next_run_at) if next_run_at is not None else None),
    })
    item["auto_download_history"] = history[:10]
    if next_run_at is None:
        item["auto_download_next_run_at"] = None
    elif hasattr(next_run_at, "isoformat"):
        item["auto_download_next_run_at"] = next_run_at.isoformat(timespec="seconds")
    else:
        item["auto_download_next_run_at"] = str(next_run_at)
    item["updated_at"] = now_iso()
    return save_sqlite_creator(item)


def reset_auto_download_schedule(creator_id: int):
    item = get_sqlite_creator(creator_id)
    if not item:
        raise HTTPException(status_code=404, detail="Creator not found")
    _normalize_schedule_fields(item)
    item["auto_download_next_run_at"] = _resolve_next_run_at(item)
    item["updated_at"] = now_iso()
    return save_sqlite_creator(item)


def clear_auto_download_runtime_state(creator_id: int):
    item = get_sqlite_creator(creator_id)
    if not item:
        raise HTTPException(status_code=404, detail="Creator not found")
    item["auto_download_last_run_at"] = None
    item["auto_download_last_status"] = ""
    item["auto_download_last_message"] = ""
    item["auto_download_history"] = []
    item["auto_download_next_run_at"] = _resolve_next_run_at(item)
    item["updated_at"] = now_iso()
    return save_sqlite_creator(item)


def list_creators():
    return list_sqlite_creators()


def list_creator_summaries():
    return list_sqlite_creator_summaries()


def list_creator_options():
    return list_sqlite_creator_options()


def list_creator_page(
    *,
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
    platform: str = "",
    profile_id: int | None = None,
    enabled: str = "",
    auto_enabled: str = "",
    auto_status: str = "",
):
    return list_sqlite_creator_summaries_paginated(
        page=page,
        page_size=page_size,
        keyword=keyword,
        platform=platform,
        profile_id=profile_id,
        enabled=enabled,
        auto_enabled=auto_enabled,
        auto_status=auto_status,
    )


def get_dashboard_summary():
    return get_sqlite_dashboard_summary()


def list_due_auto_download_creators(now_value: str, limit: int | None = None):
    return list_due_sqlite_creators(now_value, limit=limit)


def get_creator(creator_id: int):
    item = get_sqlite_creator(creator_id)
    if item:
        return item
    raise HTTPException(status_code=404, detail="Creator not found")


def create_creator(payload: CreatorCreate):
    item = payload.model_dump()
    item["id"] = None
    item["profile_id"] = item["profile_id"] or 1
    _normalize_schedule_fields(item)
    item["created_at"] = now_iso()
    item["updated_at"] = item["created_at"]
    return save_sqlite_creator(item)


def update_creator(creator_id: int, payload: CreatorUpdate):
    item = get_sqlite_creator(creator_id)
    if not item:
        raise HTTPException(status_code=404, detail="Creator not found")
    schedule_snapshot = (
        item.get("auto_download_enabled"),
        item.get("auto_download_interval_minutes"),
        item.get("auto_download_start_at"),
        item.get("enabled"),
    )
    item.update(payload.model_dump())
    item["profile_id"] = item["profile_id"] or 1
    new_snapshot = (
        item.get("auto_download_enabled"),
        item.get("auto_download_interval_minutes"),
        item.get("auto_download_start_at"),
        item.get("enabled"),
    )
    if schedule_snapshot != new_snapshot:
        item["auto_download_next_run_at"] = None
    _normalize_schedule_fields(item)
    item["updated_at"] = now_iso()
    return save_sqlite_creator(item)


def delete_creator(creator_id: int):
    if not get_sqlite_creator(creator_id):
        raise HTTPException(status_code=404, detail="Creator not found")
    delete_sqlite_creator(creator_id)


def collect_creator_work_ids_for_purge(item: dict) -> list[str]:
    from .scans import map_engine_items

    work_ids: set[str] = set()
    for row in item.get("_scan_cache_rows", []):
        for work in row.get("payload") or []:
            work_id = str(work.get("id") or "").strip()
            if work_id:
                work_ids.add(work_id)
    try:
        engine_items = map_engine_items(fetch_account_items(item))
    except Exception:
        engine_items = []
    for work in engine_items:
        work_id = str(work.get("id") or "").strip()
        if work_id:
            work_ids.add(work_id)
    return sorted(work_ids)


def delete_creator_with_download_history(creator_id: int) -> dict:
    item = get_sqlite_creator(creator_id)
    if not item:
        raise HTTPException(status_code=404, detail="Creator not found")

    scan_cache_rows = list_sqlite_scan_cache(creator_id)
    item["_scan_cache_rows"] = scan_cache_rows
    work_ids = collect_creator_work_ids_for_purge(item)
    item.pop("_scan_cache_rows", None)

    if not work_ids:
        raise HTTPException(
            status_code=409,
            detail="Unable to resolve creator work IDs for download history cleanup",
        )

    deleted_count = delete_downloaded_ids(work_ids)
    delete_sqlite_creator(creator_id)
    return {
        "creator_id": creator_id,
        "resolved_work_ids": len(work_ids),
        "deleted_download_records": deleted_count,
    }
