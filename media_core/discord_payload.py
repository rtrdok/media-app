"""Low-level Discord RPC payload details not exposed by pypresence.update."""

from __future__ import annotations

import os
import time
from typing import Any


def update_paused_activity(rpc, kwargs: dict[str, Any]) -> None:
    """Send an explicit empty timestamps object to erase an old countdown.

    pypresence removes ``None`` keys, but Discord merges an omitted timestamps
    field into the previous activity. ``timestamps: {}`` is materially
    different and makes a paused activity static.
    """
    value = lambda item: getattr(item, "value", item)
    assets: dict[str, Any] = {}
    if kwargs.get("large_image"):
        assets["large_image"] = kwargs["large_image"]
    payload = {
        "cmd": "SET_ACTIVITY",
        "args": {
            "pid": os.getpid(),
            "activity": {
                "type": value(kwargs.get("activity_type")),
                "status_display_type": value(kwargs.get("status_display_type")),
                "details": kwargs.get("details"),
                "state": kwargs.get("state"),
                "name": kwargs.get("name"),
                "timestamps": {},
                "assets": assets,
                "instance": True,
            },
        },
        "nonce": f"{time.time():.20f}",
    }
    rpc.update(payload_override=payload)
