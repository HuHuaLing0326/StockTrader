"""真实联网测试：直接请求外部数据源。默认不运行，用 `pytest -m live` 显式运行。

每个测试只发很少的请求；断路器、限速器、存档都写在临时目录，不影响正式数据目录。
"""

from __future__ import annotations

import pytest

from stocktrader.data.config import load_config
from stocktrader.data.errors import SourceFailure
from stocktrader.data.health import MemoryEventSink, RequestContext
from stocktrader.data.models import AttemptOutcome, ErrorCategory
from stocktrader.data.runtime import build_runtime

pytestmark = pytest.mark.live


@pytest.fixture
def runtime(tmp_path):
    rt = build_runtime(load_config(data_dir=tmp_path, mode="test"), sink=MemoryEventSink())
    yield rt
    rt.close()


def ctx(source: str, category: str) -> RequestContext:
    return RequestContext(source=source, data_category=category, operation="live-test")


def test_tencent_quote_decodes_gbk_without_replacement_chars(runtime):
    resp = runtime.http["tencent"].get("https://qt.gtimg.cn/q=sh600519,sh688981", context=ctx("tencent.quote", "quote"),
                                       encoding="gbk")
    assert "贵州茅台" in resp.text and "中芯国际" in resp.text
    assert runtime.archive.load(runtime.sink.raw[0]) == resp.body


def test_sina_without_referer_is_blocked_once_and_stops_the_family(runtime):
    sina = runtime.http["sina"]
    with pytest.raises(SourceFailure) as err:
        sina.get("https://hq.sinajs.cn/list=sh600519", context=ctx("sina.quote", "quote"))
    assert err.value.category is ErrorCategory.BLOCKED
    assert len(runtime.sink.health) == 1  # 风控信号不重试
    with pytest.raises(SourceFailure) as again:  # 之后整个接口族冷却，不再发请求
        sina.get("https://hq.sinajs.cn/list=sh600519", context=ctx("sina.quote", "quote"),
                 headers={"Referer": "https://finance.sina.com.cn"})
    assert again.value.category is ErrorCategory.COOLDOWN and len(runtime.sink.health) == 2


def test_sina_with_referer_works(runtime):
    resp = runtime.http["sina"].get("https://hq.sinajs.cn/list=sh600519", context=ctx("sina.quote", "quote"),
                                    headers={"Referer": "https://finance.sina.com.cn"}, encoding="gbk")
    assert "贵州茅台" in resp.text


def test_akshare_sina_calendar_through_library_guard(runtime):
    import akshare as ak

    df = runtime.libraries["sina"].call(ak.tool_trade_date_hist_sina, context=ctx("sina.calendar", "calendar"))
    dates = set(df["trade_date"].astype(str))
    assert len(dates) > 8000 and "2026-10-23" in dates and "2026-10-01" not in dates
    assert runtime.sink.health[-1].status is AttemptOutcome.OK


def test_baostock_query_and_real_relogin_after_logout(runtime):
    import baostock as bs

    client = runtime.baostock
    first = client.query("query_trade_dates", "2026-10-01", "2026-10-09", context=ctx("baostock.trade_dates", "calendar"))
    assert dict(first.rows)["2026-10-01"] == "0" and dict(first.rows)["2026-10-09"] == "1"
    bs.logout()  # 在客户端不知情的情况下断开会话：实测此后查询返回 10002007
    again = client.query("query_trade_dates", "2026-10-01", "2026-10-09", context=ctx("baostock.trade_dates", "calendar"))
    assert again.rows == first.rows
    categories = [e.error_category for e in runtime.sink.health]
    assert ErrorCategory.SESSION_LOST in categories and categories[-1] is None


def test_baostock_invalid_arguments_are_a_source_error(runtime):
    with pytest.raises(SourceFailure) as err:
        runtime.baostock.query("query_history_k_data_plus", "sh.600519", "date,close", start_date="2026-13-01",
                               end_date="2026-10-02", context=ctx("baostock.k_data", "daily_bars"))
    assert err.value.category is ErrorCategory.SOURCE_ERROR


def test_baostock_unexported_risk_list(runtime):
    result = runtime.baostock.query("security.sectorinfo.query_st_stocks", "2026-10-23",
                                    context=ctx("baostock.st_list", "risk_warning"))
    assert result.fields == ("updateDate", "code", "code_name") and len(result.rows) > 50


def test_disabled_eastmoney_sends_nothing(runtime):
    with pytest.raises(SourceFailure) as err:
        runtime.http["eastmoney"].get("https://push2.eastmoney.com/api/qt/clist/get",
                                      context=ctx("eastmoney.clist", "snapshot"))
    assert err.value.category is ErrorCategory.DISABLED
