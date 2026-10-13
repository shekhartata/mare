"""Padded corpus for the cases where a hop or an exact filter beats Top-K.

The phrase that answers a bridge or distributed question is only on the hop
target. Distractors share the question's words, so hybrid K=8 is not the
database and does not have to include that target. The absence question has
no document with sku sku_plain; a lookalike mentions that token in prose.
"""

from datetime import datetime

DATABASE = "mare_utility"

_GARMENTS = (
    "linen shirt",
    "wool scarf",
    "cotton hoodie",
    "silk blouse",
    "denim jacket",
    "canvas tote",
    "leather belt",
    "nylon shorts",
    "fleece vest",
    "chambray dress",
    "corduroy pants",
    "suede gloves",
    "mesh cap",
    "satin skirt",
    "tweed coat",
    "jersey socks",
)
_LANES = (
    "harbor",
    "pinewharf",
    "redhook",
    "cobalt",
    "keel",
    "marlow",
    "osprey",
    "quill",
    "rowan",
    "sable",
    "timber",
    "umbra",
    "vellum",
    "willow",
    "yarrow",
    "zephyr",
)
_DRINKS = (
    "dark roast",
    "cold brew",
    "espresso shot",
    "chai latte",
    "green tea",
    "cocoa",
    "barley tea",
    "lemon water",
    "oat latte",
    "mint tea",
    "rye coffee",
    "decaf drip",
    "mocha",
    "black tea",
)
_SKUS = (
    "sku_linen",
    "sku_oak",
    "sku_cedar",
    "sku_flint",
    "sku_maple",
    "sku_birch",
    "sku_slate",
    "sku_ivory",
)

CASES: tuple[dict, ...] = (
    {
        "id": "util_bridge",
        "database": DATABASE,
        "title": "Bridge carrier",
        "question": (
            "A sweater was returned because it pilled after one wash. "
            "Which carrier lane handled that order?"
        ),
        "gold_sources": [{"collection": "orders", "document_id": "ord_pill"}],
        "must_contain_any": ["northwind"],
        "must_not_contain": ["unknown", "cannot", "can't"],
        "hidden": "northwind",
    },
    {
        "id": "util_distributed",
        "database": DATABASE,
        "title": "Distributed assay",
        "question": (
            "A guest reported a bitter aftertaste in the house blend. "
            "What assay finding explains it?"
        ),
        "gold_sources": [{"collection": "assays", "document_id": "lot_77"}],
        "must_contain_any": ["chlorogenic"],
        "must_not_contain": ["unknown", "cannot", "can't"],
        "hidden": "chlorogenic",
    },
    {
        "id": "util_absence",
        "database": DATABASE,
        "title": "Absence sku_plain",
        "question": "How many refunds for sku_plain were requested in April 2024?",
        "gold_sources": [],
        "must_contain_any": ["0", "zero", "none"],
        "must_not_contain": [],
        "hidden": "",
    },
)


def documents() -> dict[str, list[dict]]:
    returns = [
        {
            "_id": "ret_pill",
            "order_id": "ord_pill",
            "reason": "sweater pilled after one wash",
            "requested_at": datetime(2024, 3, 18),
        }
    ]
    orders = [
        {
            "_id": "ord_pill",
            "carrier_lane": "northwind",
            "status": "closed",
        }
    ]
    for index, garment in enumerate(_GARMENTS):
        key = f"{index:02d}"
        returns.append(
            {
                "_id": f"ret_{key}",
                "order_id": f"ord_{key}",
                "reason": f"{garment} faded after one wash",
                "requested_at": datetime(2024, 3, 2 + (index % 20)),
            }
        )
        orders.append(
            {
                "_id": f"ord_{key}",
                "carrier_lane": _LANES[index],
                "status": "closed",
            }
        )

    notes = [
        {
            "_id": "note_house",
            "lot_id": "lot_77",
            "note": "guest reported a bitter aftertaste in the house blend",
        }
    ]
    assays = [
        {
            "_id": "lot_77",
            "summary": "chlorogenic acid above the roast ceiling",
        }
    ]
    for index, drink in enumerate(_DRINKS):
        key = f"{index:02d}"
        notes.append(
            {
                "_id": f"note_{key}",
                "lot_id": f"lot_{key}",
                "note": f"guest reported a bitter aftertaste in the {drink}",
            }
        )
        assays.append(
            {
                "_id": f"lot_{key}",
                "summary": f"batch {key} within the usual acidity band",
            }
        )

    refunds = [
        {
            "_id": "ref_look",
            "sku": "sku_plain_plus",
            "reason": "replacement for sku_plain style mug",
            "requested_at": datetime(2024, 4, 12),
        },
        {
            "_id": "ref_jan",
            "sku": "sku_linen",
            "reason": "hem came loose before spring",
            "requested_at": datetime(2024, 1, 9),
        },
    ]
    for index, sku in enumerate(_SKUS):
        refunds.append(
            {
                "_id": f"ref_{index:02d}",
                "sku": sku,
                "reason": f"{sku} seam split in transit",
                "requested_at": datetime(2024, 4, 3 + index),
            }
        )
    return {
        "returns": returns,
        "orders": orders,
        "notes": notes,
        "assays": assays,
        "refunds": refunds,
    }
