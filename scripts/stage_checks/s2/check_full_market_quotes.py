"""S2 一次性验证：以生产规模通过传输层请求一遍全市场腾讯报价。

核对：每批都按 GBK 无替换字符解码；请求的每只股票都有返回；相邻请求的间隔不小于配置；原始响应全部存档。
用法：.venv/Scripts/python.exe scripts/stage_checks/s2/check_full_market_quotes.py
使用测试模式（data/test/），不影响真实数据目录。代码清单来自实测阶段保存的 baostock 全量名单。
"""

from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

import pandas as pd

from stocktrader.data.config import load_config
from stocktrader.data.health import MemoryEventSink, RequestContext
from stocktrader.data.runtime import build_runtime
from stocktrader.data.security import Kind, parse, to_source_code

ROOT = Path(__file__).resolve().parents[3]
BASIC_CSV = ROOT / "data" / "probes" / "20261025" / "bs_stock_basic.csv"


def main() -> int:
    config = load_config(mode="test")
    family = config.families["tencent"]
    basic = pd.read_csv(BASIC_CSV, dtype=str)
    listed = basic[(basic["type"] == "1") & (basic["status"] == "1")]["code"]
    codes = [to_source_code(parse(c, Kind.STOCK), "tencent") for c in listed]
    batches = [codes[i:i + config.snapshot_batch_size] for i in range(0, len(codes), config.snapshot_batch_size)]
    print(f"在市股票 {len(codes)} 只，批量 {config.snapshot_batch_size}，共 {len(batches)} 次请求；"
          f"最小间隔 {family.min_interval_s}s + 抖动 {family.jitter_s}")

    sink = MemoryEventSink()
    runtime = build_runtime(config, sink=sink)
    returned, bad_lines, started = set(), [], time.monotonic()
    try:
        for i, batch in enumerate(batches):
            resp = runtime.http["tencent"].get(
                "https://qt.gtimg.cn/q=" + ",".join(batch), encoding="gbk",
                context=RequestContext("tencent.quote", "snapshot", "stage-check-s2"))
            for line in resp.text.strip().split(";"):
                if '"' not in line:
                    continue
                key = line.split("=")[0].strip().split("_")[-1]
                fields = line.split('"')[1].split("~")
                returned.add(key)
                if len(fields) < 88:
                    bad_lines.append((key, len(fields)))
    finally:
        runtime.close()
    elapsed = time.monotonic() - started

    events = [e for e in sink.health if e.context.source == "tencent.quote"]
    starts = [e.event_at - timedelta(milliseconds=e.elapsed_ms) for e in events]
    gaps = [(s - prev.event_at).total_seconds() for prev, s in zip(events, starts[1:])]
    missing = sorted(set(codes) - returned)
    raw_bytes = sum(r.byte_size for r in sink.raw)

    print(f"用时 {elapsed:.1f}s；请求 {len(events)} 次，失败 {sum(e.status != 'OK' for e in events)} 次")
    print(f"返回 {len(returned)} 只，缺失 {len(missing)} 只 {missing[:10]}；字段数不足 88 的 {len(bad_lines)} 行 {bad_lines[:5]}")
    print(f"相邻请求间隔：最小 {min(gaps):.3f}s，最大 {max(gaps):.3f}s（配置最小 {family.min_interval_s}s）")
    print(f"原始响应存档 {len(sink.raw)} 份，共 {raw_bytes / 1e6:.2f} MB（压缩前）")
    ok = (not missing and not bad_lines and len(events) == len(batches)
          and min(gaps) >= family.min_interval_s - 0.01 and len(sink.raw) == len(batches))
    print("结论：", "通过" if ok else "不通过")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
