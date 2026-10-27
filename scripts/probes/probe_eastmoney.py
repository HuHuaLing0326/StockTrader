"""Probe Eastmoney with a minimal number of throttled requests (IP-ban prone).

Uses the same URLs and params akshare uses (stock_zh_a_spot_em, stock_zh_a_hist,
index_zh_a_hist), but fetches only one snapshot page instead of all ~59.
"""

from __future__ import annotations

import json

from _common import decode, get, record

CLIST_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
CLIST_PARAMS = {
    "pn": "1", "pz": "100", "po": "1", "np": "1", "ut": "bd1d9ddb04089700cf9c27f6f7426281",
    "fltt": "2", "invt": "2", "fid": "f12",
    "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
    "fields": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21,f23,f24,f25,f22,f11,f62,"
              "f128,f136,f115,f152",
}


def probe_clist() -> None:
    resp = get("eastmoney", "em_clist_page1", CLIST_URL, params=CLIST_PARAMS)
    text, enc = decode(resp.content, "utf-8")
    try:
        data = json.loads(text).get("data") or {}
    except json.JSONDecodeError as exc:
        record("em_clist_page1", status=resp.status_code, json_error=str(exc), head=text[:200], **enc)
        return
    diff = data.get("diff") or []
    rows = diff if isinstance(diff, list) else list(diff.values())
    moutai = next((r for r in rows if r.get("f12") == "600519"), None)
    record("em_clist_page1", status=resp.status_code, total=data.get("total"), rows=len(rows),
           first=rows[0] if rows else None, moutai=moutai, **enc)


def probe_kline(name: str, secid: str, fqt: str) -> None:
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": "101", "fqt": fqt, "secid": secid, "beg": "20261019", "end": "20261023",
    }
    resp = get("eastmoney", name, KLINE_URL, params=params)
    text, enc = decode(resp.content, "utf-8")
    try:
        data = json.loads(text).get("data") or {}
    except json.JSONDecodeError as exc:
        record(name, status=resp.status_code, json_error=str(exc), head=text[:200], **enc)
        return
    klines = data.get("klines") or []
    record(name, status=resp.status_code, code=data.get("code"), name_=data.get("name"), rows=len(klines),
           first=klines[0] if klines else None, last=klines[-1] if klines else None, **enc)


if __name__ == "__main__":
    probe_clist()
    probe_kline("em_kline_600519_raw", "1.600519", "0")
    probe_kline("em_kline_600519_qfq", "1.600519", "1")
    probe_kline("em_kline_index_000300", "1.000300", "0")
