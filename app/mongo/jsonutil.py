from __future__ import annotations

import json
from typing import Any

from bson import json_util


def jsonable(doc: Any) -> Any:
    return json.loads(json_util.dumps(doc))
