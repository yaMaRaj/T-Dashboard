"""Application paths and runtime constants.

ROOT_DIR points at the monorepo root (…/T-Dashboard), not apps/server.
"""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]
SERVER_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
LOG_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "tdashboard.db"
SHARED_DIR = ROOT_DIR / "shared"

DATA_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH.as_posix()}"
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
