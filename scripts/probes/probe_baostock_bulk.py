"""Probe baostock bulk-by-date endpoints and the unexported ST / risk / delisting lists."""

from __future__ import annotations

import baostock as bs
from baostock.security import sectorinfo

from _common import record
from probe_baostock import query


def main() -> None:
    lg = bs.login()
    record("baostock_login", error_code=lg.error_code, error_msg=lg.error_msg)
    try:
        for day in ("2026-10-23", "2020-06-01", "2015-07-08"):
            df = query(f"bs_daily_k_astock_{day}", bs.query_daily_history_k_AStock, day)
            if not df.empty:
                row = df[df["code"].isin(["sh.600519", "600519"])].head(1).to_dict("records")
                record(f"bs_daily_k_astock_{day}_check", moutai=row,
                       tradestatus_counts=df["tradestatus"].value_counts().to_dict()
                       if "tradestatus" in df.columns else None)
        query("bs_daily_k_etf_2026-10-23", bs.query_daily_history_k_ETF, "2026-10-23")

        adj = query("bs_daily_adjust_factor_20251219", bs.query_daily_adjust_factor, "2025-12-19")
        if not adj.empty:
            record("bs_daily_adjust_factor_moutai", rows=adj[adj["code"] == "sh.600519"].to_dict("records"))
        query("bs_adjust_factor_600519_recent", bs.query_adjust_factor, "sh.600519", "2024-01-01", "2026-10-23")

        for name in ("query_st_stocks", "query_starst_stocks", "query_stocks_in_risk",
                     "query_suspended_stocks", "query_terminated_stocks"):
            fn = getattr(sectorinfo, name)
            query(f"bs_{name}_20261023", fn, "2026-10-23")
            query(f"bs_{name}_20200601", fn, "2020-06-01")

        now_ind = query("bs_industry_current", bs.query_stock_industry)
        old_ind = query("bs_industry_20200102", bs.query_stock_industry, "", "2020-01-02")
        if not now_ind.empty and not old_ind.empty:
            merged = now_ind.merge(old_ind, on="code", suffixes=("_now", "_2020"))
            changed = merged[merged["industry_now"] != merged["industry_2020"]]
            record("bs_industry_history_diff", common=len(merged), changed=len(changed),
                   update_dates_now=sorted(now_ind["updateDate"].unique())[-3:],
                   update_dates_2020=sorted(old_ind["updateDate"].unique())[-3:],
                   classifications=sorted(now_ind["industryClassification"].unique()),
                   example=changed.head(2).to_dict("records"))
    finally:
        bs.logout()


if __name__ == "__main__":
    main()
