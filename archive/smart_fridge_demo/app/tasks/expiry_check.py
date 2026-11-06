from __future__ import annotations

from app.database.connection import database, init_db
from app.database.repositories import inventory_repository
from app.services.notification_service import build_expiry_message


def run() -> list[str]:
    init_db()
    with database() as connection:
        batches = inventory_repository.list_batches(connection)
    return [
        build_expiry_message(item["name"], item["days_until_expiry"])
        for item in batches
        if item.get("days_until_expiry") is not None and item["days_until_expiry"] <= 3
    ]


if __name__ == "__main__":
    for message in run():
        print(message)
