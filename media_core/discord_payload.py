"""Wire-level Discord RPC payloads for nullable activity fields."""

from __future__ import annotations

import os
import time
from typing import Any


def update_paused_activity(rpc, kwargs: dict[str, Any]) -> None:
    """Publish a paused activity with an explicit empty timestamps object.

    Discord treats an omitted field as a partial update and keeps the previous
    timer. Local Discord RPC validates timestamps as an object (not null), so
    this one payload must be sent directly with ``timestamps: {}``.
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
