"""Small warehouse corpus. Almost no prose. Scored by document ids and counts."""

from datetime import datetime

GOLD = (
    ("Where is bin_a3?", ("bin_a3",), None),
    ("How many movements of sku_bolt are recorded?", ("mov_1",), 1),
    ("How many movements of sku_bolt happened in April 2024?", (), 0),
    ("Which sku is stored in bin_a3?", ("sku_bolt",), None),
)


def documents() -> dict[str, list[dict]]:
    return {
        "skus": [
            {"_id": "sku_bolt", "name": "M8 bolt"},
            {"_id": "sku_nut", "name": "Hex nut"},
        ],
        "bins": [
            {"_id": "bin_a3", "code": "A3", "sku": "sku_bolt"},
            {"_id": "bin_b1", "code": "B1", "sku": "sku_nut"},
        ],
        "movements": [
            {
                "_id": "mov_1",
                "sku": "sku_bolt",
                "bin_code": "A3",
                "qty": 10,
                "moved_at": datetime(2024, 1, 15),
            },
            {
                "_id": "mov_2",
                "sku": "sku_nut",
                "bin_code": "B1",
                "qty": 4,
                "moved_at": datetime(2024, 6, 1),
            },
            {
                "_id": "mov_3",
                "sku": "sku_nut",
                "bin_code": "B1",
                "qty": 1,
                "moved_at": datetime(2024, 4, 2),
            },
        ],
    }
