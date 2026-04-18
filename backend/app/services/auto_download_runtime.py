import asyncio
from datetime import datetime, timedelta

from ..config import AUTO_DOWNLOAD_MAX_CONCURRENCY, AUTO_DOWNLOAD_WORK_BATCH_SIZE
from ..schemas import DownloadWorksTaskCreate
from . import scans
from .auto_download_throttle import is_auto_download_paused
from .panel_config import read_panel_config
from .creators import get_creator, list_due_auto_download_creators, update_auto_download_result
from .engine import fetch_account_items
from .risk_guard import is_risk_guard_active
from .tasks import create_auto_works_download_task, has_running_task_for_creator


CHECK_INTERVAL_SECONDS = 45
RUNNING_CREATORS: set[int] = set()
AUTO_DOWNLOAD_WAKE_EVENT: asyncio.Event | None = None


def bind_auto_download_wake_event(event: asyncio.Event) -> None:
    global AUTO_DOWNLOAD_WAKE_EVENT
    AUTO_DOWNLOAD_WAKE_EVENT = event


def request_auto_download_wakeup() -> None:
    if AUTO_DOWNLOAD_WAKE_EVENT:
        AUTO_DOWNLOAD_WAKE_EVENT.set()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _next_run_after(creator: dict, base: datetime | None = None) -> datetime | None:
    interval = max(0, int(creator.get("auto_download_interval_minutes") or 0))
    if interval <= 0 or not creator.get("auto_download_enabled"):
        return None
    start_at = _parse_dt(creator.get("auto_download_start_at"))
    anchor = base or datetime.now()
    if start_at and start_at > anchor:
        return start_at
    return anchor + timedelta(minutes=interval)


def _scan_creator_once(creator_id: int) -> tuple[dict, list[str]]:
    creator = get_creator(creator_id)
    engine_items = scans.map_engine_items(fetch_account_items(creator))
    payload = scans.build_scan_payload(creator, engine_items, "engine_api_auto")
    work_ids = [item.id for item in payload["items"] if not item.is_downloaded]
    return payload, work_ids


def _split_work_ids(work_ids: list[str]) -> list[list[str]]:
    config = read_panel_config()
    size = max(
        1,
        int(config.get("auto_download_work_batch_size") or AUTO_DOWNLOAD_WORK_BATCH_SIZE),
    )
    return [work_ids[index:index + size] for index in range(0, len(work_ids), size)]


async def run_once_for_creator(creator: dict) -> None:
    creator_id = creator["id"]
    if creator_id in RUNNING_CREATORS:
        return
    if await asyncio.to_thread(is_auto_download_paused) or await asyncio.to_thread(is_risk_guard_active):
        return
    RUNNING_CREATORS.add(creator_id)
    try:
        if await asyncio.to_thread(has_running_task_for_creator, creator_id):
            await asyncio.to_thread(
                update_auto_download_result,
                creator_id,
                status="skipped",
                message="已有运行中的任务，本轮自动下载已跳过。",
                next_run_at=_next_run_after(creator),
                mark_run=False,
            )
            return

        payload, work_ids = await asyncio.to_thread(_scan_creator_once, creator_id)
        creator = await asyncio.to_thread(get_creator, creator_id)
        if not work_ids:
            await asyncio.to_thread(
                update_auto_download_result,
                creator_id,
                status="idle",
                message=f"扫描完成，未发现新作品。总数 {payload['all_count']}，已下载 {payload['downloaded_count']}。",
                next_run_at=_next_run_after(creator),
            )
            return

        batches = _split_work_ids(work_ids)
        for batch_work_ids in batches:
            await asyncio.to_thread(
                create_auto_works_download_task,
                DownloadWorksTaskCreate(creator_id=creator_id, work_ids=batch_work_ids),
            )
        await asyncio.to_thread(
            update_auto_download_result,
            creator_id,
            status="scheduled",
            message=(
                f"扫描完成，新增待下载作品 {len(work_ids)} 个，"
                f"已拆分为 {len(batches)} 个批次加入任务队列。"
            ),
            next_run_at=_next_run_after(creator),
        )
    except Exception as error:
        await asyncio.to_thread(
            update_auto_download_result,
            creator_id,
            status="failed",
            message=f"自动下载失败：{error}",
            next_run_at=_next_run_after(creator),
        )
    finally:
        RUNNING_CREATORS.discard(creator_id)


async def _wait_for_next_cycle(stop_event: asyncio.Event) -> None:
    wake_event = AUTO_DOWNLOAD_WAKE_EVENT
    if wake_event is None:
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CHECK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
        return
    stop_task = asyncio.create_task(stop_event.wait())
    wake_task = asyncio.create_task(wake_event.wait())
    try:
        done, pending = await asyncio.wait(
            {stop_task, wake_task},
            timeout=CHECK_INTERVAL_SECONDS,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except asyncio.TimeoutError:
        pass
    finally:
        if wake_event.is_set():
            wake_event.clear()


async def scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        if await asyncio.to_thread(is_auto_download_paused) or await asyncio.to_thread(is_risk_guard_active):
            await _wait_for_next_cycle(stop_event)
            continue

        now = datetime.now()
        due_creators = [
            creator
            for creator in await asyncio.to_thread(
                list_due_auto_download_creators,
                now.isoformat(timespec="seconds"),
                AUTO_DOWNLOAD_MAX_CONCURRENCY * 4,
            )
            if creator["id"] not in RUNNING_CREATORS
        ]

        if due_creators:
            slots = max(1, AUTO_DOWNLOAD_MAX_CONCURRENCY - len(RUNNING_CREATORS))
            batch = due_creators[:slots]
            if batch:
                for creator in batch:
                    if await asyncio.to_thread(is_auto_download_paused) or await asyncio.to_thread(is_risk_guard_active):
                        break
                    await run_once_for_creator(creator)
                continue
        await _wait_for_next_cycle(stop_event)
