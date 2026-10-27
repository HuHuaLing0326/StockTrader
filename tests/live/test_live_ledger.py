"""全链路联网测试：按配置组装运行环境 → 真实请求 → 事件文件 → 导入 DuckDB → 健康统计。"""

from __future__ import annotations

import pytest

from stocktrader.data.config import load_config
from stocktrader.data.health import RequestContext
from stocktrader.data.ledger import ingest_events, source_health
from stocktrader.data.runtime import build_runtime
from stocktrader.data.store import Store

pytestmark = pytest.mark.live


def test_real_requests_flow_into_the_ledger(tmp_path):
    config = load_config(data_dir=tmp_path, mode="test")
    runtime = build_runtime(config)  # 默认的 JSONL 事件文件
    store = Store.from_config(config)
    store.initialize()
    try:
        runtime.http["tencent"].get("https://qt.gtimg.cn/q=sh600519", encoding="gbk",
                                    context=RequestContext("tencent.quote", "quote", "live-test", code="600519"))
        calendar = runtime.baostock.query("query_trade_dates", "2026-10-01", "2026-10-09",
                                          context=RequestContext("baostock.trade_dates", "calendar", "live-test"))
    finally:
        runtime.close()
    report = ingest_events(store, config.paths.events_dir)
    assert report.health_events == 2 and report.raw_records == 2
    health = {h.source: h for h in source_health(store, hours=1)}
    assert health["tencent.quote"].ok == 1 and health["baostock.trade_dates"].ok == 1
    with store.read() as r:
        rows = dict(r.query("SELECT source, row_count FROM source_health_events"))
    # baostock 交易日历对每个自然日都返回一行并标明是否开市（实测记录第四节），10-01 至 10-09 共 9 行
    assert rows["baostock.trade_dates"] == 9
    flags = dict(calendar.rows)
    assert flags["2026-10-01"] == "0" and flags["2026-10-09"] == "1"
