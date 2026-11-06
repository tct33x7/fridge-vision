from __future__ import annotations

import shutil
from datetime import datetime

from app.config import BACKUP_DIR, DB_PATH


def run() -> str | None:
    if not DB_PATH.exists():
        return None
    target = BACKUP_DIR / f"smart_fridge_{datetime.now():%Y%m%d_%H%M%S}.db"
    shutil.copy2(DB_PATH, target)
    return str(target)


if __name__ == "__main__":
    print(run() or "数据库尚未创建")
