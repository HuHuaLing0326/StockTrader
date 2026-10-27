"""Probe mootdx (TDX TCP protocol): server reachability, daily bars, index bars, quotes, finance."""

from __future__ import annotations

import socket
import time
from pathlib import Path

import pandas as pd

from _common import record

SERVERS = [
    ("119.97.185.59", 7709), ("124.70.133.119", 7709), ("116.205.183.150", 7709), ("123.60.73.44", 7709),
    ("116.205.163.254", 7709), ("121.36.225.169", 7709), ("123.60.70.228", 7709), ("124.71.9.153", 7709),
    ("110.41.147.114", 7709), ("124.71.187.122", 7709),
]


def frame_summary(df) -> dict:
    if df is None:
        return {"type": "None"}
    if not isinstance(df, pd.DataFrame):
        return {"type": type(df).__name__, "value": str(df)[:300]}
    return {
        "rows": len(df),
        "columns": list(df.columns),
        "index_name": df.index.name,
        "head": df.head(1).reset_index().astype(str).to_dict("records"),
        "tail": df.tail(1).reset_index().astype(str).to_dict("records"),
    }


def timed(name: str, fn, *args, **kwargs):
    started = time.monotonic()
    try:
        out = fn(*args, **kwargs)
    except Exception as exc:  # probe: record every failure mode
        record(name, error=f"{type(exc).__name__}: {exc}", elapsed_s=round(time.monotonic() - started, 3))
        return None
    record(name, elapsed_s=round(time.monotonic() - started, 3), **frame_summary(out))
    time.sleep(0.3)
    return out


def main() -> None:
    reachable = []
    for ip, port in SERVERS:
        started = time.monotonic()
        try:
            with socket.create_connection((ip, port), timeout=2.0):
                reachable.append((ip, port, round(time.monotonic() - started, 3)))
        except OSError as exc:
            record("tdx_server_probe", server=f"{ip}:{port}", error=type(exc).__name__)
    record("tdx_servers_reachable", servers=reachable)
    if not reachable:
        return

    config_path = Path.home() / ".mootdx" / "config.json"
    config_before = config_path.exists()
    from mootdx.quotes import Quotes

    ip, port, _ = min(reachable, key=lambda r: r[2])
    started = time.monotonic()
    client = Quotes.factory(market="std", server=(ip, port))
    record("tdx_client_init", server=f"{ip}:{port}", elapsed_s=round(time.monotonic() - started, 3),
           config_path=str(config_path), config_existed_before=config_before, config_exists_after=config_path.exists())

    timed("tdx_bars_600519_latest", client.bars, symbol="600519", frequency=9, offset=5)
    timed("tdx_bars_600519_page2", client.bars, symbol="600519", frequency=9, start=800, offset=5)
    timed("tdx_bars_600519_offset1000", client.bars, symbol="600519", frequency=9, offset=1000)
    timed("tdx_bars_etf_510300", client.bars, symbol="510300", frequency=9, offset=3)
    timed("tdx_index_bars_000300_auto_market", client.index_bars, symbol="000300", frequency=9, offset=3)
    timed("tdx_index_bars_000001_auto_market", client.index_bars, symbol="000001", frequency=9, offset=3)
    timed("tdx_index_000300_market_sh", client.index, symbol="000300", market=1, frequency=9, offset=3)
    timed("tdx_quotes", client.quotes, symbol=["600519", "000001", "300750"])
    timed("tdx_finance_600519", client.finance, symbol="600519")


if __name__ == "__main__":
    main()
