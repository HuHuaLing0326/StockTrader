"""S3 一次性验证：按生产规模写入一年的全市场日线，测量写入、重复写入、冲突检测与读取的耗时。

数据形态与生产一致：真实的在市股票代码（5224 只）、baostock 返回的真实交易日；价格为按规则生成的合理值
（本验证关心的是规模与写入通道的行为，不是价格本身）。
用法：.venv/Scripts/python.exe scripts/stage_checks/s3/check_store_at_scale.py [交易日数，默认 243]
数据库建在 data/test/stage_s3/，结束后删除。
"""

from __future__ import annotations

import random
import shutil
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

from stocktrader.data import clock
from stocktrader.data.config import load_config
from stocktrader.data.health import MemoryEventSink, RequestContext
from stocktrader.data.runtime import build_runtime
from stocktrader.data.store import Store

ROOT = Path(__file__).resolve().parents[3]
BASIC_CSV = ROOT / "data" / "probes" / "20261025" / "bs_stock_basic.csv"


def trading_days_2025(config) -> list[date]:
    runtime = build_runtime(config, sink=MemoryEventSink())
    try:
        result = runtime.baostock.query("query_trade_dates", "2025-01-01", "2025-12-31",
                                        context=RequestContext("baostock.trade_dates", "calendar", "stage-check-s3"))
    finally:
        runtime.close()
    return [date.fromisoformat(d) for d, is_open in result.rows if is_open == "1"]


def bars_for_day(codes: list[tuple[str, str]], day: date, rng: random.Random) -> list[dict]:
    fetched = clock.at(day, clock.MARKET_CLOSE).replace(hour=18)
    rows = []
    for code, exchange in codes:
        pre = rng.uniform(3, 300)
        close = pre * rng.uniform(0.9, 1.1)
        high, low = max(pre, close) * rng.uniform(1, 1.03), min(pre, close) * rng.uniform(0.97, 1)
        volume = rng.uniform(1e5, 1e8)
        rows.append({
            "code": code, "exchange": exchange, "kind": "STOCK", "trade_date": day,
            "open": pre, "high": high, "low": low, "close": close, "pre_close": pre,
            "volume_raw": volume, "volume_raw_unit": "SHARE", "volume_shares": volume,
            "amount_raw": volume * close, "amount_raw_unit": "CNY", "amount_cny": volume * close,
            "pct_chg": (close / pre - 1) * 100, "pct_chg_computed": False, "turnover_pct": rng.uniform(0.1, 10),
            "completeness": "COMPLETE", "missing_fields": [], "source": "baostock", "fetched_at": fetched,
            "batch_id": f"s3-{day:%Y%m%d}",
        })
    return rows


def main(days_wanted: int) -> int:
    config = load_config(mode="test")
    basic = pd.read_csv(BASIC_CSV, dtype=str)
    listed = basic[(basic["type"] == "1") & (basic["status"] == "1")]["code"]
    codes = [(c[3:], "SSE" if c.startswith("sh.") else "SZSE") for c in listed]
    days = trading_days_2025(config)[:days_wanted]
    root = config.paths.root / "stage_s3"
    shutil.rmtree(root, ignore_errors=True)
    store = Store(root / "market.duckdb", root / "market.lock", config.store_lock_timeout_s)
    store.initialize()
    print(f"股票 {len(codes)} 只 × 交易日 {len(days)} 天 = {len(codes) * len(days):,} 行")

    rng, timings, first_day_rows = random.Random(20251231), [], None
    try:
        for i, day in enumerate(days):
            rows = bars_for_day(codes, day, rng)
            if i == 0:
                first_day_rows = rows
            started = time.monotonic()
            with store.write_batch() as batch:
                report = batch.upsert("daily_bars", rows)
            timings.append(time.monotonic() - started)
            assert report.inserted == len(rows), report
            if i in (0, len(days) // 2, len(days) - 1):
                print(f"  第 {i + 1:3d} 天 {day}：写入 {report.inserted} 行用时 {timings[-1]:.2f}s")

        started = time.monotonic()
        with store.write_batch() as batch:
            rerun = batch.upsert("daily_bars", first_day_rows)
        rerun_s = time.monotonic() - started
        changed = [dict(r) for r in first_day_rows]
        changed[0]["close"] += 0.01
        started = time.monotonic()
        with store.write_batch() as batch:
            conflict = batch.upsert("daily_bars", changed)
        conflict_s = time.monotonic() - started

        code, exchange = codes[0]
        started = time.monotonic()
        with store.read() as r:
            history = r.query("SELECT trade_date, close FROM daily_bars WHERE code = ? AND exchange = ? AND kind = 'STOCK' "
                              "ORDER BY trade_date", [code, exchange])
        history_s = time.monotonic() - started
        started = time.monotonic()
        with store.read() as r:
            section = r.query("SELECT code, close FROM daily_bars WHERE trade_date = ?", [days[-1]])
            total, distinct_keys, conflicts = r.query(
                "SELECT count(*), count(DISTINCT (kind, code, exchange, trade_date, source)), "
                "(SELECT count(*) FROM data_conflicts) FROM daily_bars")[0]
        section_s = time.monotonic() - started
        size_mb = (root / "market.duckdb").stat().st_size / 1e6
    finally:
        shutil.rmtree(root, ignore_errors=True)

    first10, last10 = statistics.mean(timings[:10]), statistics.mean(timings[-10:])
    print(f"每批写入：前 10 批平均 {first10:.2f}s，后 10 批平均 {last10:.2f}s，最慢 {max(timings):.2f}s")
    print(f"满表时重复写入一天：{rerun.unchanged} 行无变化，用时 {rerun_s:.2f}s")
    print(f"满表时冲突检测：{conflict.conflicts} 条冲突，用时 {conflict_s:.2f}s")
    print(f"读取一只股票全年 {len(history)} 行用时 {history_s:.3f}s；读取一天截面 {len(section)} 行用时 {section_s:.3f}s")
    print(f"总行数 {total:,}，唯一键 {distinct_keys:,}，冲突记录 {conflicts}；数据库文件 {size_mb:.0f} MB")
    years_estimate = 2700 / len(days)
    print(f"按 2015 年至今约 2700 个交易日估算：文件约 {size_mb * years_estimate / 1e3:.1f} GB，"
          f"首次写入约 {sum(timings) * years_estimate / 60:.0f} 分钟（不含下载）")
    ok = (rerun.unchanged == len(codes) and conflict.conflicts == 1 and total == distinct_keys == len(codes) * len(days)
          and conflicts == 1 and len(history) == len(days) and len(section) == len(codes))
    print("结论：", "通过" if ok else "不通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 243))
