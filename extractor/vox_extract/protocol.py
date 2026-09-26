"""Build the phone's feature message (android/PROTOCOL.md, v1) from events, and optionally send it
to the app's debug socket (after `adb forward tcp:7788 localabstract:vox-debug`).

One sound per message with device timing, as the device will do; the phone groups sounds into
sequences with t_start_ms / t_end_ms (gap_ms, default 600).
"""

from __future__ import annotations

import json
import socket


def message(events: list[dict], msg_id: int, mode: str = "gesture", armed: bool = True, features: bool = False) -> dict:
    """features=True adds the optional per-sound `features` list (fp1 fingerprint + pitch16, FINGERPRINT.md) when
    the events carry a fingerprint; an event without one gets null."""
    if not 0 < len(events) <= 3:
        raise ValueError("1-3 sounds per message")
    m = {
        "v": 1,
        "id": msg_id,
        "mode": mode,
        "armed": armed,
        "sounds": [e["text"] for e in events],
        "sequence": [e["label"] for e in events],
        "timing": [{"t_start_ms": int(e["t_start_ms"]), "t_end_ms": int(e["t_end_ms"])} for e in events],
        "phrase": None,
        "cursor": None,
    }
    if features:
        from .fingerprint import features_entry
        feats = [features_entry(e.get("raw") or {}) for e in events]
        if any(f is not None for f in feats):
            m["features"] = feats
    return m


class DebugSocket:
    """Newline-delimited JSON to the app's debug socket; returns the app's reply line."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7788, timeout: float = 3.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.f = self.sock.makefile("rw", encoding="utf-8", newline="\n")

    def send(self, msg: dict) -> str:
        self.f.write(json.dumps(msg) + "\n")
        self.f.flush()
        return self.f.readline().strip()

    def close(self) -> None:
        self.sock.close()
