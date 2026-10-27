"""Probe Tencent realtime quotes (qt.gtimg.cn) and daily klines (fqkline)."""

from __future__ import annotations

import json

from _common import decode, get, record

QUOTE_URL = "https://qt.gtimg.cn/q="
FQKLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

# stock (SH main, SZ main, ChiNext, STAR), index (SH, SZ, CSI 300), ETF (SH, SZ), BSE
QUOTE_CODES = [
    "sh600519", "sz000001", "sz300750", "sh688981",
    "sh000001", "sz399001", "sh000300",
    "sh510300", "sz159915",
    "bj430047",
]


def probe_quotes() -> None:
    resp = get("tencent", "tencent_quote", QUOTE_URL + ",".join(QUOTE_CODES))
    text, enc = decode(resp.content, "gbk")
    record("tencent_quote", status=resp.status_code, **enc)
    for line in text.strip().split(";"):
        line = line.strip()
        if "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        values = line.split('"')[1].split("~")
        record("tencent_quote_line", key=key, field_count=len(values))
        if key in ("sh600519", "sh000300", "sh510300", "sz300750"):
            record("tencent_quote_fields", key=key, fields={i: v for i, v in enumerate(values)})


def fqkline(name: str, param: str) -> dict:
    resp = get("tencent", name, FQKLINE_URL, params={"param": param})
    text, enc = decode(resp.content, "utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        record(name, param=param, status=resp.status_code, json_error=str(exc), head=text[:200], **enc)
        return {}
    code = param.split(",")[0]
    data = (payload.get("data") or {}).get(code)
    if not isinstance(data, dict):
        record(name, param=param, status=resp.status_code, top_keys=list(payload), data_type=type(data).__name__,
               head=text[:200], **enc)
        return {}
    summary = {}
    for key in ("day", "qfqday", "hfqday"):
        rows = data.get(key)
        if rows:
            summary[key] = {
                "rows": len(rows),
                "row_lengths": sorted({len(r) for r in rows}),
                "first": rows[0],
                "last": rows[-1],
                "long_row_example": next((r for r in rows if len(r) > 6), None),
            }
    record(name, param=param, status=resp.status_code, data_keys=list(data), series=summary, **enc)
    return data


def probe_klines() -> None:
    window = "2025-10-20,2026-10-23"
    fqkline("tencent_kline_stock_raw", f"sh600519,day,{window},320,")
    fqkline("tencent_kline_stock_qfq", f"sh600519,day,{window},320,qfq")
    fqkline("tencent_kline_stock_raw_no_trailing_comma", f"sh600519,day,{window},320")
    fqkline("tencent_kline_index_raw", f"sh000300,day,{window},320,")
    fqkline("tencent_kline_index_qfq", f"sh000300,day,{window},320,qfq")
    fqkline("tencent_kline_etf_raw", f"sh510300,day,{window},320,")
    fqkline("tencent_kline_etf_qfq", f"sh510300,day,{window},320,qfq")
    fqkline("tencent_kline_stock_raw_long", "sh600519,day,2015-01-01,2026-10-23,3000,")


if __name__ == "__main__":
    probe_quotes()
    probe_klines()
