"""Small shop corpus. No SaaS fields. Scored by document ids and counts."""

from datetime import datetime

GOLD = (
    ("What is the status of order ord_1044?", ("ord_1044",), None),
    (
        "Which order was refunded because a sweater pilled after one wash?",
        ("ord_1044",),
        None,
    ),
    ("How many refunds are for sku_wool?", ("ref_9",), 1),
    ("How many refunds are for sku_mug?", (), 0),
)


def documents() -> dict[str, list[dict]]:
    return {
        "products": [
            {"_id": "sku_wool", "name": "Wool sweater", "price": 80},
            {"_id": "sku_mug", "name": "Ceramic mug", "price": 12},
        ],
        "orders": [
            {
                "_id": "ord_1044",
                "status": "shipped",
                "placed_at": datetime(2024, 3, 2),
                "sku": "sku_wool",
                "line_items": [{"sku": "sku_wool", "qty": 1}],
            },
            {
                "_id": "ord_2001",
                "status": "placed",
                "placed_at": datetime(2024, 4, 1),
                "sku": "sku_mug",
                "line_items": [{"sku": "sku_mug", "qty": 2}],
            },
        ],
        "refunds": [
            {
                "_id": "ref_9",
                "order_id": "ord_1044",
                "sku": "sku_wool",
                "reason": "sweater pilled after one wash",
                "requested_at": datetime(2024, 3, 18),
            }
        ],
    }
