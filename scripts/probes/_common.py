"""Shared helpers for one-off data-source probes.

Not production code. Every probe request is throttled per source family, its
raw response is saved under data/probes/<date>/, and a metadata line is
appended to requests.jsonl so the findings can be audited later.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

BEIJING = ZoneInfo("Asia/Shanghai")
REPLACEMENT_CHAR = chr(0xFFFD)  # what errors="replace" inserts for undecodable bytes
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "probes" / datetime.now(BEIJING).strftime("%Y%m%d")
OUT.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# Seconds between two requests to the same family; jitter is added on top.
MIN_INTERVAL = {"eastmoney": 1.5, "sina": 1.0, "tencent": 0.5, "cninfo": 1.0}
_last_call: dict[str, float] = {}
_sessions: dict[str, requests.Session] = {}


def _throttle(family: str) -> None:
    wait = MIN_INTERVAL.get(family, 1.0) - (time.monotonic() - _last_call.get(family, 0.0))
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.4))


def _session(family: str) -> requests.Session:
    if family not in _sessions:
        session = requests.Session()
        session.headers["User-Agent"] = UA
        session.trust_env = False  # market sources: never route through a system proxy
        _sessions[family] = session
    return _sessions[family]


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def get(
    family: str,
    name: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 15,
) -> requests.Response:
    """Throttled GET; saves the raw body and logs request metadata."""

    _throttle(family)
    started = time.monotonic()
    error = None
    resp = None
    try:
        resp = _session(family).get(url, params=params, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        _last_call[family] = time.monotonic()
    elapsed = round(time.monotonic() - started, 3)
    meta: dict[str, Any] = {
        "at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "family": family,
        "name": name,
        "url": url,
        "params": params,
        "elapsed_s": elapsed,
    }
    if resp is not None:
        body = resp.content
        (OUT / f"{_safe_name(name)}.bin").write_bytes(body)
        meta |= {
            "status": resp.status_code,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "content_type": resp.headers.get("Content-Type"),
            "final_url": resp.url,
        }
    else:
        meta["error"] = error
    with (OUT / "requests.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
    if resp is None:
        raise RuntimeError(f"{name}: {error}")
    return resp


def decode(body: bytes, encoding: str) -> tuple[str, dict[str, Any]]:
    """Decode and report replacement characters, judged on the characters themselves."""

    text = body.decode(encoding, errors="replace")
    return text, {"encoding": encoding, "chars": len(text), "replacement_chars": text.count(REPLACEMENT_CHAR)}


def record(probe: str, **fields: Any) -> None:
    """Append one finding to findings.jsonl and echo it."""

    line = {"probe": probe, **fields}
    with (OUT / "findings.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    print(json.dumps(line, ensure_ascii=False, default=str))
