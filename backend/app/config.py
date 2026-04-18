import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("NEWWEB_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
TASK_LOG_DIR = DATA_DIR / "task_logs"
TASK_LOG_DIR.mkdir(parents=True, exist_ok=True)
TASK_RUNTIME_DIR = DATA_DIR / "task_runtime"
TASK_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

APP_DB_PATH = DATA_DIR / "panel_store.json"
APP_SQLITE_PATH = DATA_DIR / "panel_store.sqlite3"
ENGINE_PROJECT_ROOT = BASE_DIR.parent
ENGINE_MAIN_PATH = ENGINE_PROJECT_ROOT / "main.py"
WORKER_DETAIL_PATH = BASE_DIR / "backend" / "app" / "worker_detail_download.py"
WORKER_ISOLATED_MAIN_PATH = BASE_DIR / "backend" / "app" / "worker_isolated_main.py"
WORKER_ISOLATED_DETAIL_PATH = BASE_DIR / "backend" / "app" / "worker_isolated_detail.py"
ENGINE_VOLUME_PATH = Path(os.getenv("ENGINE_VOLUME_PATH", ENGINE_PROJECT_ROOT / "Volume"))
ENGINE_DB_PATH = ENGINE_VOLUME_PATH / "DouK-Downloader.db"
ENGINE_SETTINGS_PATH = ENGINE_VOLUME_PATH / "settings.json"
ENGINE_API_BASE = os.getenv("ENGINE_API_BASE", "http://127.0.0.1:5555")
ENGINE_API_TOKEN = os.getenv("ENGINE_API_TOKEN", "")
AUTO_DOWNLOAD_MAX_CONCURRENCY = max(1, int(os.getenv("AUTO_DOWNLOAD_MAX_CONCURRENCY", "1")))
DOWNLOADED_IDS_CACHE_SECONDS = max(1, int(os.getenv("DOWNLOADED_IDS_CACHE_SECONDS", "30")))
MAX_SCAN_CACHE_PER_CREATOR = max(1, int(os.getenv("MAX_SCAN_CACHE_PER_CREATOR", "3")))
AUTO_DOWNLOAD_TASK_MAX_CONCURRENCY = max(1, int(os.getenv("AUTO_DOWNLOAD_TASK_MAX_CONCURRENCY", "1")))
AUTO_DOWNLOAD_WORK_BATCH_SIZE = max(1, int(os.getenv("AUTO_DOWNLOAD_WORK_BATCH_SIZE", "20")))
TASK_DISPATCH_INTERVAL_SECONDS = max(1, int(os.getenv("TASK_DISPATCH_INTERVAL_SECONDS", "5")))
TASK_RUNTIME_RETENTION_SECONDS = max(60, int(os.getenv("TASK_RUNTIME_RETENTION_SECONDS", "1800")))
TASK_RUNTIME_CLEANUP_INTERVAL_SECONDS = max(5, int(os.getenv("TASK_RUNTIME_CLEANUP_INTERVAL_SECONDS", "30")))

APP_NAME = "NEWWEB Control Panel API"
APP_VERSION = "0.1.0"
