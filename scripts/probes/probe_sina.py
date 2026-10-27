"""Probe Sina realtime quotes, the full-market snapshot pages, and the trade calendar."""

from __future__ import annotations

import json

from _common import decode, get, record

QUOTE_URL = "https://hq.sinajs.cn/list="
REFERER = {"Referer": "https://finance.sina.com.cn"}
SNAPSHOT_URL = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
SNAPSHOT_COUNT_URL = (
    "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
)
QUOTE_CODES = ["sh600519", "sz000001", "sz300750", "sh000300", "sh510300", "bj430047"]


def probe_quotes() -> None:
    url = QUOTE_URL + ",".join(QUOTE_CODES)
    resp = get("sina", "sina_quote_no_referer", url)
    text, enc = decode(resp.content, "gbk")
    record("sina_quote_no_referer", status=resp.status_code, head=text[:120], **enc)

    resp = get("sina", "sina_quote", url, headers=REFERER)
    text, enc = decode(resp.content, "gbk")
    record("sina_quote", status=resp.status_code, **enc)
    for line in text.strip().split(";"):
        line = line.strip()
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        values = line.split('"')[1].split(",")
        record("sina_quote_line", key=key, field_count=len(values))
        if key in ("sh600519", "sh000300", "sh510300"):
            record("sina_quote_fields", key=key, fields={i: v for i, v in enumerate(values)})


def probe_snapshot() -> None:
    resp = get("sina", "sina_snapshot_count", SNAPSHOT_COUNT_URL, params={"node": "hs_a"}, headers=REFERER)
    text, enc = decode(resp.content, "gbk")
    record("sina_snapshot_count", status=resp.status_code, body=text[:80], **enc)

    for num in (80, 500):
        params = {"page": "1", "num": str(num), "sort": "symbol", "asc": "1", "node": "hs_a", "symbol": "",
                  "_s_r_a": "page"}
        resp = get("sina", f"sina_snapshot_page1_num{num}", SNAPSHOT_URL, params=params, headers=REFERER)
        charset = (resp.headers.get("Content-Type") or "").lower()
        text, enc = decode(resp.content, "gbk" if "gb" in charset else "utf-8")
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as exc:
            record(f"sina_snapshot_num{num}", status=resp.status_code, content_type=charset, json_error=str(exc),
                   head=text[:200], **enc)
            continue
        record(f"sina_snapshot_num{num}", status=resp.status_code, content_type=charset, rows=len(rows),
               keys=list(rows[0]) if rows else None, first=rows[0] if rows else None, **enc)


def probe_calendar() -> None:
    import akshare as ak

    df = ak.tool_trade_date_hist_sina()
    dates = df["trade_date"].astype(str)
    record(
        "sina_calendar",
        rows=len(df),
        first=dates.iloc[0],
        last=dates.iloc[-1],
        dtype=str(df["trade_date"].dtype),
        has_2026_10_01=bool((dates == "2026-10-01").any()),
        has_2026_10_09=bool((dates == "2026-10-09").any()),
        has_2026_10_23=bool((dates == "2026-10-23").any()),
        tail=list(dates.iloc[-5:]),
    )


if __name__ == "__main__":
    probe_quotes()
    probe_snapshot()
    probe_calendar()
