from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import PROCESSED_DIR


def run(days: int = 30) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    for path in PROCESSED_DIR.iterdir():
        if not path.is_file() or path.name == ".gitkeep":
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            path.unlink()
            removed += 1
    return removed


if __name__ == "__main__":
    print(f"已清理 {run()} 个过期预处理文件")
