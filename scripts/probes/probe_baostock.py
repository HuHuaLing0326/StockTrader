"""Probe baostock: calendar, security lists, daily bars, adjust factors, ST/industry by date."""

from __future__ import annotations

import time

import baostock as bs
import pandas as pd

from _common import record

KLINE_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST"
INDEX_FIELDS = "date,code,open,high,low,close,preclose,volume,amount,pctChg"


def query(name: str, fn, *args, **kwargs) -> pd.DataFrame:
    started = time.monotonic()
    rs = fn(*args, **kwargs)
    elapsed = round(time.monotonic() - started, 3)
    if rs.error_code != "0":
        record(name, error_code=rs.error_code, error_msg=rs.error_msg, elapsed_s=elapsed)
        return pd.DataFrame()
    # rs.get_data() calls DataFrame.append (removed in pandas 2) once a result spans
    # more than one page, so read rows one by one instead.
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    df = pd.DataFrame(rows, columns=rs.fields)
    record(name, rows=len(df), fields=list(df.columns), elapsed_s=round(time.monotonic() - started, 3),
           head=df.head(2).to_dict("records"), tail=df.tail(1).to_dict("records"))
    time.sleep(0.3)
    return df


def main() -> None:
    lg = bs.login()
    record("baostock_login", error_code=lg.error_code, error_msg=lg.error_msg)
    try:
        cal = query("bs_trade_dates_2026", bs.query_trade_dates, "2026-01-01", "2026-12-31")
        if not cal.empty:
            lookup = dict(zip(cal["calendar_date"], cal["is_trading_day"]))
            record("bs_trade_dates_check", last=cal["calendar_date"].iloc[-1],
                   d_2026_10_01=lookup.get("2026-10-01"), d_2026_10_09=lookup.get("2026-10-09"),
                   d_2026_10_23=lookup.get("2026-10-23"), d_2026_10_24=lookup.get("2026-10-24"))
        query("bs_trade_dates_2027", bs.query_trade_dates, "2027-01-01", "2027-01-31")

        basic = query("bs_stock_basic", bs.query_stock_basic)
        if not basic.empty:
            record("bs_stock_basic_counts", type_counts=basic["type"].value_counts().to_dict(),
                   status_counts=basic["status"].value_counts().to_dict(),
                   delisted_example=basic[basic["status"] == "0"].head(2).to_dict("records"))
        allst = query("bs_all_stock_20261023", bs.query_all_stock, "2026-10-23")
        if not allst.empty:
            record("bs_all_stock_tradestatus", counts=allst["tradeStatus"].value_counts().to_dict())

        window = ("2025-10-20", "2026-10-23")
        for flag, label in (("3", "raw"), ("2", "qfq"), ("1", "hfq")):
            query(f"bs_kline_600519_{label}", bs.query_history_k_data_plus, "sh.600519", KLINE_FIELDS,
                  start_date=window[0], end_date=window[1], frequency="d", adjustflag=flag)
        query("bs_kline_index_000300", bs.query_history_k_data_plus, "sh.000300", INDEX_FIELDS,
              start_date=window[0], end_date=window[1], frequency="d", adjustflag="3")
        query("bs_kline_etf_510300", bs.query_history_k_data_plus, "sh.510300", INDEX_FIELDS,
              start_date=window[0], end_date=window[1], frequency="d", adjustflag="3")

        query("bs_adjust_factor_600519", bs.query_adjust_factor, "sh.600519", "2015-01-01", "2026-10-23")
        query("bs_daily_adjust_factor_20251219", bs.query_daily_adjust_factor, "2025-12-19")

        query("bs_st_20261023", bs.query_st_stocks, "2026-10-23")
        query("bs_st_20200601", bs.query_st_stocks, "2020-06-01")
        query("bs_suspended_listing_20261023", bs.query_suspended_stocks, "2026-10-23")
        query("bs_terminated_20261023", bs.query_terminated_stocks, "2026-10-23")

        now_ind = query("bs_industry_current", bs.query_stock_industry)
        old_ind = query("bs_industry_20200102", bs.query_stock_industry, "", "2020-01-02")
        if not now_ind.empty and not old_ind.empty:
            merged = now_ind.merge(old_ind, on="code", suffixes=("_now", "_2020"))
            changed = merged[merged["industry_now"] != merged["industry_2020"]]
            record("bs_industry_history_diff", common=len(merged), changed=len(changed),
                   update_dates_now=sorted(now_ind["updateDate"].unique())[-3:],
                   update_dates_2020=sorted(old_ind["updateDate"].unique())[-3:],
                   example=changed.head(2).to_dict("records"))
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
