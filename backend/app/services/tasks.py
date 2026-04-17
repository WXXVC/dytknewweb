import asyncio
import contextlib
import subprocess
import sys
import threading
import json
import shutil
from pathlib import Path
from shutil import copy2
from datetime import datetime, timedelta

from fastapi import HTTPException

from ..config import (
    AUTO_DOWNLOAD_TASK_MAX_CONCURRENCY,
    ENGINE_PROJECT_ROOT,
    ENGINE_DB_PATH,
    ENGINE_VOLUME_PATH,
    TASK_DISPATCH_INTERVAL_SECONDS,
    TASK_LOG_DIR,
    TASK_RUNTIME_DIR,
    TASK_RUNTIME_CLEANUP_INTERVAL_SECONDS,
    TASK_RUNTIME_RETENTION_SECONDS,
    WORKER_ISOLATED_DETAIL_PATH,
    WORKER_ISOLATED_MAIN_PATH,
)
from ..db import get_sqlite_task, list_sqlite_scan_cache, list_sqlite_tasks, next_sqlite_task_id, now_iso, save_sqlite_task
from ..db import count_sqlite_tasks, delete_sqlite_tasks_by_creator, list_sqlite_task_summaries, list_sqlite_task_summaries_paginated, list_sqlite_tasks_by_statuses
from ..schemas import DownloadTaskCreate, DownloadWorksTaskCreate
from .auto_download_throttle import is_auto_download_paused, record_auto_download_progress
from .creators import clear_auto_download_runtime_state, collect_creator_work_ids_for_purge, get_creator, list_creators
from .engine import (
    build_run_command,
    build_settings_payload,
    delete_downloaded_ids,
    fetch_account_items,
    normalize_download_root,
    read_downloaded_ids,
    read_engine_settings,
)
from .profiles import get_profile
from .risk_guard import (
    assess_low_quality_items,
    detect_empty_download,
    extract_status_codes,
    is_risk_guard_active,
    record_empty_download_signal,
    record_http_error_signal,
    record_low_quality_signal,
)
from .scans import build_scan_payload, find_scan_items_by_work_ids, infer_creator_folder_name, map_engine_items


PROCESS_REGISTRY: dict[int, dict] = {}
TASK_LAUNCH_LOCK = threading.Lock()
TERMINAL_TASK_STATUSES = {"success", "failed", "stopped"}


def has_running_task_for_creator(creator_id: int) -> bool:
    running_count = count_sqlite_tasks(creator_id=creator_id, status="running")
    if running_count:
        for task in list_sqlite_tasks_by_statuses(
            creator_id=creator_id,
            statuses=("running",),
        ):
            if _task_status(task)["status"] == "running":
                return True
    return count_sqlite_tasks(creator_id=creator_id, status="queued") > 0


def count_running_auto_tasks() -> int:
    for task in list_sqlite_tasks_by_statuses(
        mode="auto_detail_download",
        statuses=("running",),
    ):
        _task_status(task)
    return count_sqlite_tasks(mode="auto_detail_download", status="running")


def _task_status(task: dict) -> dict:
    entry = PROCESS_REGISTRY.get(task["id"])
    process = entry["process"] if entry else None
    if process and task["status"] == "running":
        code = process.poll()
        if code is None:
            return task
        task["status"] = "success" if code == 0 else "failed"
        task["message"] = (
            "Downloader process finished successfully"
            if code == 0
            else f"Downloader process exited with code {code}"
        )
        task["exit_code"] = code
        _evaluate_completed_task_risk(task)
        _record_completed_auto_download_progress(task)
        task["updated_at"] = now_iso()
        save_sqlite_task(task)
        _finalize_registry_entry(task["id"])
    return task


def list_tasks():
    return [_task_status(task) for task in list_sqlite_tasks()]


def list_task_summaries():
    return list_sqlite_task_summaries()


def list_task_page(
    *,
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
    status: str = "",
    mode: str = "",
    kind: str = "",
):
    return list_sqlite_task_summaries_paginated(
        page=page,
        page_size=page_size,
        keyword=keyword,
        status=status,
        mode=mode,
        kind=kind,
    )


def list_task_center_summary_page(
    *,
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
):
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 10)))
    creators = list_creators()
    tasks = list_sqlite_tasks()
    downloaded_ids = read_downloaded_ids(force_refresh=True)

    def classify_work_type(value: str) -> str:
        text = str(value or "").strip().lower()
        if "live" in text or "实况" in text:
            return "live"
        if "collection" in text or "图集" in text:
            return "collection"
        return "video"

    work_type_by_creator: dict[int, dict[str, str]] = {}
    for creator in creators:
        creator_id = int(creator["id"])
        work_type_map: dict[str, str] = {}
        for row in list_sqlite_scan_cache(creator_id):
            for item in row.get("payload") or []:
                work_id = str(item.get("id") or "").strip()
                if not work_id:
                    continue
                work_type_map[work_id] = classify_work_type(item.get("type") or "")
        work_type_by_creator[creator_id] = work_type_map

    summaries: dict[int, dict] = {
        int(creator["id"]): {
            "creator_id": int(creator["id"]),
            "creator_name": creator.get("name") or "",
            "platform": creator.get("platform") or "",
            "mark": creator.get("mark") or "",
            "video_ids": set(),
            "collection_ids": set(),
            "live_ids": set(),
            "failed_count": 0,
            "last_download_at": None,
        }
        for creator in creators
    }

    for task in tasks:
        creator_id = int(task.get("creator_id") or 0)
        if not creator_id:
            continue
        summary = summaries.setdefault(
            creator_id,
            {
                "creator_id": creator_id,
                "creator_name": task.get("creator_name") or f"账号 {creator_id}",
                "platform": task.get("platform") or "",
                "mark": "",
                "video_ids": set(),
                "collection_ids": set(),
                "live_ids": set(),
                "failed_count": 0,
                "last_download_at": None,
            },
        )

        if task.get("status") == "failed":
            summary["failed_count"] += 1

        work_ids = [str(item) for item in (task.get("work_ids") or []) if item]
        if not work_ids:
            continue

        success_work_ids = [work_id for work_id in work_ids if work_id in downloaded_ids]
        if not success_work_ids:
            continue

        updated_at = task.get("updated_at") or task.get("created_at")
        work_type_map = work_type_by_creator.setdefault(creator_id, {})
        matched_items = find_scan_items_by_work_ids(creator_id, success_work_ids)
        for item in matched_items:
            if item.get("id"):
                work_type_map[str(item["id"])] = classify_work_type(item.get("type") or "")
        for work_id in success_work_ids:
            item_type = classify_work_type(work_type_map.get(work_id, ""))
            if item_type == "collection":
                summary["collection_ids"].add(work_id)
            elif item_type == "live":
                summary["live_ids"].add(work_id)
            else:
                summary["video_ids"].add(work_id)
        if updated_at and (summary["last_download_at"] is None or str(updated_at) > str(summary["last_download_at"])):
            summary["last_download_at"] = updated_at

    items = []
    keyword_text = str(keyword or "").strip().lower()
    for summary in summaries.values():
        creator_name = summary["creator_name"]
        mark = summary["mark"]
        if keyword_text and keyword_text not in f"{creator_name} {mark} {summary['platform']}".lower():
            continue
        items.append(
            {
                "creator_id": summary["creator_id"],
                "creator_name": creator_name,
                "platform": summary["platform"],
                "mark": mark,
                "video_count": len(summary["video_ids"]),
                "collection_count": len(summary["collection_ids"]),
                "live_count": len(summary["live_ids"]),
                "failed_count": int(summary["failed_count"] or 0),
                "last_download_at": summary["last_download_at"],
            }
        )

    items.sort(key=lambda item: ((item["last_download_at"] or ""), item["creator_id"]), reverse=True)
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _list_pending_work_ids_for_creator(creator: dict) -> list[str]:
    try:
        engine_items = map_engine_items(fetch_account_items(creator))
        payload = build_scan_payload(creator, engine_items, "engine_api_batch_preview")
        return [item.id for item in payload["items"] if not item.is_downloaded]
    except Exception:
        return []


def list_running_task_cards() -> list[dict]:
    downloaded_ids = read_downloaded_ids(force_refresh=True)
    items: list[dict] = []
    for task in list_sqlite_tasks_by_statuses(statuses=("running",), order_asc=False):
        current = _task_status(task)
        if current.get("status") != "running":
            continue
        work_ids = [str(item) for item in (current.get("work_ids") or []) if item]
        total_count = max(0, int(current.get("item_count") or 0))
        if work_ids:
            total_count = max(total_count, len(work_ids))
            completed_count = sum(1 for work_id in work_ids if work_id in downloaded_ids)
        else:
            completed_count = 0
        progress_percent = min(100, int((completed_count / total_count) * 100)) if total_count > 0 else 0
        items.append(
            {
                "task_id": int(current["id"]),
                "creator_id": int(current["creator_id"]),
                "creator_name": current.get("creator_name") or f"账号 {current['creator_id']}",
                "platform": current.get("platform") or "",
                "mode": current.get("mode") or "",
                "total_count": total_count,
                "completed_count": completed_count,
                "progress_percent": progress_percent,
                "target_folder_name": current.get("target_folder_name") or "",
                "message": current.get("message") or "",
            }
        )
    return items


def get_task(task_id: int):
    task = get_sqlite_task(task_id)
    if task:
        return _task_status(task)
    raise HTTPException(status_code=404, detail="Task not found")


def _finalize_registry_entry(task_id: int) -> None:
    entry = PROCESS_REGISTRY.pop(task_id, None)
    if not entry:
        return
    for handle_name in ("stdout", "stderr"):
        handle = entry.get(handle_name)
        if handle and not handle.closed:
            handle.close()


def _read_log_text(path_value: str) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _evaluate_completed_task_risk(task: dict) -> None:
    stdout_text = _read_log_text(task.get("stdout_log", ""))
    stderr_text = _read_log_text(task.get("stderr_log", ""))
    raw_text = f"{stdout_text}\n{stderr_text}"
    status_codes = extract_status_codes(raw_text)
    record_http_error_signal(status_codes, raw_text)
    record_empty_download_signal(detect_empty_download(raw_text))


def _record_completed_auto_download_progress(task: dict) -> None:
    if task.get("mode") != "auto_detail_download" or task.get("status") != "success":
        return
    work_ids = [str(item) for item in (task.get("work_ids") or []) if item]
    if not work_ids:
        return
    downloaded_ids = read_downloaded_ids(force_refresh=True)
    success_count = sum(1 for work_id in work_ids if work_id in downloaded_ids)
    if success_count <= 0:
        return
    throttle_state = record_auto_download_progress(
        creators_count=1,
        works_count=success_count,
    )
    if throttle_state.get("last_reason"):
        task["message"] = f"{task.get('message') or 'Downloader process finished successfully'} {throttle_state['last_reason']}".strip()


def _ensure_shared_db_link(target_volume: Path) -> None:
    shared_db = ENGINE_DB_PATH
    target_db = target_volume / "DouK-Downloader.db"
    if target_db.exists():
        return
    if shared_db.exists():
        try:
            target_db.hardlink_to(shared_db)
            return
        except Exception:
            try:
                target_db.symlink_to(shared_db)
                return
            except Exception:
                copy2(shared_db, target_db)
                return
    target_db.touch(exist_ok=True)


def _prepare_task_volume(task_id: int, settings: dict) -> Path:
    volume_path = TASK_RUNTIME_DIR / f"task_{task_id}" / "Volume"
    volume_path.mkdir(parents=True, exist_ok=True)
    _ensure_shared_db_link(volume_path)
    settings_path = volume_path / "settings.json"
    settings_path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8-sig" if sys.platform.startswith("win") else "utf-8",
    )
    return volume_path


def _start_process_with_logs(task_id: int, command: list[str], cwd: str) -> tuple[subprocess.Popen, str, str, object, object]:
    stdout_path = TASK_LOG_DIR / f"task_{task_id}_stdout.log"
    stderr_path = TASK_LOG_DIR / f"task_{task_id}_stderr.log"
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=stdout_handle,
        stderr=stderr_handle,
    )
    return process, str(stdout_path), str(stderr_path), stdout_handle, stderr_handle


def _append_task(task: dict) -> dict:
    return save_sqlite_task(task)


def _resolve_download_root(profile: dict, settings: dict) -> str:
    profile_root = normalize_download_root(profile.get("root_path") or "")
    if profile_root:
        return profile_root
    engine_root = str(settings.get("root") or "").strip()
    if engine_root:
        return engine_root
    return str(ENGINE_VOLUME_PATH)


def _launch_creator_batch_task(task_id: int, creator: dict, profile: dict, work_ids: list[str] | None = None) -> dict:
    settings = read_engine_settings()
    settings.update(build_settings_payload(profile, [creator]))
    settings["root"] = _resolve_download_root(profile, settings)
    settings["run_command"] = build_run_command(creator["platform"])
    volume_path = _prepare_task_volume(task_id, settings)
    if not WORKER_ISOLATED_MAIN_PATH.exists():
        raise HTTPException(status_code=500, detail="Isolated main worker script not found")
    process, stdout_log, stderr_log, stdout_handle, stderr_handle = _start_process_with_logs(
        task_id,
        [sys.executable, str(WORKER_ISOLATED_MAIN_PATH), "--volume", str(volume_path)],
        str(ENGINE_PROJECT_ROOT),
    )
    task = {
        "id": task_id,
        "creator_id": creator["id"],
        "creator_name": creator["name"],
        "platform": creator["platform"],
        "profile_id": profile["id"],
        "status": "running",
        "mode": "creator_batch_download",
        "item_count": len(work_ids or []),
        "run_command": settings["run_command"],
        "pid": process.pid,
        "message": "Downloader process started",
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
        "exit_code": None,
        "runtime_volume_path": str(volume_path),
        "runtime_volume_cleaned_at": None,
        "work_ids": list(work_ids or []),
    }
    PROCESS_REGISTRY[task_id] = {
        "process": process,
        "stdout": stdout_handle,
        "stderr": stderr_handle,
    }
    return task


def _launch_detail_task(task_id: int, creator: dict, profile: dict, work_ids: list[str], mode: str) -> dict:
    settings = read_engine_settings()
    settings.update(build_settings_payload(profile, [creator]))
    settings["root"] = _resolve_download_root(profile, settings)
    target_folder_name = profile["folder_name"]
    if mode in {"detail_download", "auto_detail_download"}:
        target_folder_name = infer_creator_folder_name(creator)
        settings["folder_name"] = target_folder_name
    volume_path = _prepare_task_volume(task_id, settings)
    if not WORKER_ISOLATED_DETAIL_PATH.exists():
        raise HTTPException(status_code=500, detail="Isolated detail worker script not found")
    command = [
        sys.executable,
        str(WORKER_ISOLATED_DETAIL_PATH),
        "--volume",
        str(volume_path),
        "--platform",
        creator["platform"],
        "--ids",
        *work_ids,
    ]
    process, stdout_log, stderr_log, stdout_handle, stderr_handle = _start_process_with_logs(
        task_id,
        command,
        str(ENGINE_PROJECT_ROOT),
    )
    task = {
        "id": task_id,
        "creator_id": creator["id"],
        "creator_name": creator["name"],
        "platform": creator["platform"],
        "profile_id": profile["id"],
        "status": "running",
        "mode": mode,
        "item_count": len(work_ids),
        "run_command": "detail-worker " + " ".join(work_ids),
        "pid": process.pid,
        "message": "Auto detail download worker started" if mode == "auto_detail_download" else "Detail download worker started",
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
        "exit_code": None,
        "runtime_volume_path": str(volume_path),
        "runtime_volume_cleaned_at": None,
        "work_ids": work_ids,
        "target_folder_name": target_folder_name,
    }
    PROCESS_REGISTRY[task_id] = {
        "process": process,
        "stdout": stdout_handle,
        "stderr": stderr_handle,
    }
    return task


def _build_queued_auto_task(task_id: int, creator: dict, profile: dict, work_ids: list[str], created_at: str) -> dict:
    target_folder_name = infer_creator_folder_name(creator)
    return {
        "id": task_id,
        "creator_id": creator["id"],
        "creator_name": creator["name"],
        "platform": creator["platform"],
        "profile_id": profile["id"],
        "status": "queued",
        "mode": "auto_detail_download",
        "item_count": len(work_ids),
        "run_command": "detail-worker " + " ".join(work_ids),
        "pid": None,
        "message": "Auto task queued, waiting for available slot",
        "stdout_log": "",
        "stderr_log": "",
        "exit_code": None,
        "runtime_volume_path": "",
        "runtime_volume_cleaned_at": None,
        "work_ids": work_ids,
        "target_folder_name": target_folder_name,
        "created_at": created_at,
        "updated_at": created_at,
    }


def create_download_task(payload: DownloadTaskCreate):
    if is_risk_guard_active():
        raise HTTPException(status_code=409, detail="Risk guard cooldown is active")
    creator = get_creator(payload.creator_id)
    profile = get_profile(payload.profile_id or creator.get("profile_id") or 1)
    work_ids = _list_pending_work_ids_for_creator(creator)
    created_at = now_iso()
    task_id = next_sqlite_task_id()
    with TASK_LAUNCH_LOCK:
        task = _launch_creator_batch_task(task_id, creator, profile, work_ids)
    task["created_at"] = created_at
    task["updated_at"] = created_at
    _append_task(task)
    return task


def create_works_download_task(payload: DownloadWorksTaskCreate):
    if is_risk_guard_active():
        raise HTTPException(status_code=409, detail="Risk guard cooldown is active")
    creator = get_creator(payload.creator_id)
    profile = get_profile(creator.get("profile_id") or 1)
    record_low_quality_signal(
        assess_low_quality_items(find_scan_items_by_work_ids(payload.creator_id, payload.work_ids))
    )
    if is_risk_guard_active():
        raise HTTPException(status_code=409, detail="Risk guard cooldown is active")
    created_at = now_iso()
    task_id = next_sqlite_task_id()
    with TASK_LAUNCH_LOCK:
        task = _launch_detail_task(task_id, creator, profile, payload.work_ids, "detail_download")
    task["created_at"] = created_at
    task["updated_at"] = created_at
    _append_task(task)
    return task


def create_auto_works_download_task(payload: DownloadWorksTaskCreate):
    if is_risk_guard_active():
        raise HTTPException(status_code=409, detail="Risk guard cooldown is active")
    creator = get_creator(payload.creator_id)
    profile = get_profile(creator.get("profile_id") or 1)
    record_low_quality_signal(
        assess_low_quality_items(find_scan_items_by_work_ids(payload.creator_id, payload.work_ids))
    )
    if is_risk_guard_active():
        raise HTTPException(status_code=409, detail="Risk guard cooldown is active")
    created_at = now_iso()
    task_id = next_sqlite_task_id()
    if count_running_auto_tasks() >= AUTO_DOWNLOAD_TASK_MAX_CONCURRENCY:
        return save_sqlite_task(
            _build_queued_auto_task(task_id, creator, profile, payload.work_ids, created_at)
        )
    with TASK_LAUNCH_LOCK:
        task = _launch_detail_task(task_id, creator, profile, payload.work_ids, "auto_detail_download")
    task["created_at"] = created_at
    task["updated_at"] = created_at
    return save_sqlite_task(task)


def dispatch_queued_auto_tasks() -> int:
    started = 0
    if is_auto_download_paused() or is_risk_guard_active():
        return started
    available_slots = max(0, AUTO_DOWNLOAD_TASK_MAX_CONCURRENCY - count_running_auto_tasks())
    if available_slots <= 0:
        return started
    queued_tasks = [
        task for task in list_sqlite_tasks_by_statuses(
            mode="auto_detail_download",
            statuses=("queued",),
            limit=available_slots,
            order_asc=True,
        )
        if task.get("status") == "queued"
    ]
    for task in reversed(queued_tasks):
        if started >= available_slots:
            break
        creator = get_creator(task["creator_id"])
        profile = get_profile(task.get("profile_id") or creator.get("profile_id") or 1)
        with TASK_LAUNCH_LOCK:
            launched = _launch_detail_task(
                task["id"],
                creator,
                profile,
                list(task.get("work_ids") or []),
                "auto_detail_download",
            )
        launched["created_at"] = task.get("created_at") or now_iso()
        launched["updated_at"] = now_iso()
        save_sqlite_task(launched)
        started += 1
    return started


async def task_dispatcher_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(dispatch_queued_auto_tasks)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TASK_DISPATCH_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


def _parse_task_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(value)
    return None


def cleanup_task_runtime_dirs() -> int:
    cleaned = 0
    cutoff = datetime.now() - timedelta(seconds=TASK_RUNTIME_RETENTION_SECONDS)
    for task in list_tasks():
        runtime_volume_value = task.get("runtime_volume_path") or ""
        if not runtime_volume_value:
            continue
        runtime_volume_path = Path(runtime_volume_value)
        if not runtime_volume_path:
            continue
        if task.get("status") not in TERMINAL_TASK_STATUSES:
            continue
        if task.get("runtime_volume_cleaned_at"):
            continue
        updated_at = _parse_task_datetime(task.get("updated_at"))
        if updated_at and updated_at > cutoff:
            continue
        runtime_root = runtime_volume_path.parent
        if runtime_root.exists():
            shutil.rmtree(runtime_root, ignore_errors=True)
        task["runtime_volume_cleaned_at"] = now_iso()
        task["updated_at"] = now_iso()
        save_sqlite_task(task)
        cleaned += 1
    return cleaned


async def task_runtime_cleanup_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        await asyncio.to_thread(cleanup_task_runtime_dirs)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TASK_RUNTIME_CLEANUP_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


def stop_task(task_id: int):
    task = get_sqlite_task(task_id)
    if task:
        if task.get("status") == "queued":
            task["status"] = "stopped"
            task["message"] = "Queued auto task cancelled by user"
            task["updated_at"] = now_iso()
            save_sqlite_task(task)
            return task
        entry = PROCESS_REGISTRY.get(task_id)
        process = entry["process"] if entry else None
        if not process or process.poll() is not None:
            return _task_status(task)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        task["status"] = "stopped"
        task["message"] = "Downloader process terminated by user"
        task["exit_code"] = process.returncode
        task["updated_at"] = now_iso()
        save_sqlite_task(task)
        _finalize_registry_entry(task_id)
        return task
    raise HTTPException(status_code=404, detail="Task not found")


def clear_creator_task_records(creator_id: int, purge_download_history: bool = False) -> dict:
    creator = get_creator(creator_id)
    affected_tasks = list_sqlite_tasks_by_statuses(creator_id=creator_id)
    stopped_count = 0
    for task in affected_tasks:
        if task.get("status") in {"running", "queued"}:
            current = stop_task(int(task["id"]))
            if current.get("status") == "stopped":
                stopped_count += 1
    deleted_count = delete_sqlite_tasks_by_creator(creator_id)
    deleted_download_records = 0
    resolved_work_ids = 0
    if purge_download_history:
        creator["_scan_cache_rows"] = list_sqlite_scan_cache(creator_id)
        work_ids = collect_creator_work_ids_for_purge(creator)
        creator.pop("_scan_cache_rows", None)
        if work_ids:
            resolved_work_ids = len(work_ids)
            deleted_download_records = delete_downloaded_ids(work_ids)
    clear_auto_download_runtime_state(creator_id)
    return {
        "creator_id": creator_id,
        "stopped_task_count": stopped_count,
        "deleted_task_count": deleted_count,
        "purged_download_history": bool(purge_download_history),
        "resolved_work_ids": resolved_work_ids,
        "deleted_download_records": deleted_download_records,
    }
