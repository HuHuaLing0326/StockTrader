"""S1 一次性验证：规则表对 baostock 全量证券名单的覆盖；腾讯报价成交量在各板块的单位。

用法：.venv/Scripts/python.exe scripts/stage_checks/s1/check_rules_and_lot_size.py
依赖实测阶段保存的 data/probes/20261025/bs_stock_basic.csv；第二项会请求腾讯和新浪各 1 次。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import requests

from stocktrader.data.errors import InvalidSecurity
from stocktrader.data.security import Board, Exchange, Kind, parse, to_source_code
from stocktrader.data.units import SHARES_PER_LOT

ROOT = Path(__file__).resolve().parents[3]
BASIC_CSV = ROOT / "data" / "probes" / "20261025" / "bs_stock_basic.csv"
BS_KIND = {"1": Kind.STOCK, "2": Kind.INDEX, "5": Kind.ETF}  # 4 为可转债，不在规则表范围内


def check_rule_table() -> bool:
    df = pd.read_csv(BASIC_CSV, dtype=str)
    ok, failures = Counter(), []
    for row in df.itertuples():
        kind = BS_KIND.get(row.type)
        if kind is None:
            continue
        try:
            sec = parse(row.code, kind)  # baostock 写法 sh.600519，自带交易所
        except InvalidSecurity as exc:
            failures.append((row.code, row.code_name, kind.value, row.status, str(exc)))
            continue
        expected = Exchange.SSE if row.code.startswith("sh.") else Exchange.SZSE
        if sec.exchange is not expected:
            failures.append((row.code, row.code_name, kind.value, row.status, f"交易所判断为 {sec.exchange}"))
            continue
        ok[(kind.value, sec.exchange.value, sec.board.value if sec.board else "-")] += 1
    print("== 规则表核对（baostock 全量，含退市）")
    for key, count in sorted(ok.items()):
        print(f"  通过 {key}: {count}")
    print(f"  失败: {len(failures)}")
    for item in failures[:20]:
        print("   ", item)
    return not failures


def check_lot_size() -> bool:
    """腾讯报价成交量的单位：科创板为股，其他板块为手（2026-10-25 与 baostock、新浪核对得出）。"""

    codes = {"sh688981": Kind.STOCK, "sh688111": Kind.STOCK, "sz300750": Kind.STOCK, "sh600519": Kind.STOCK,
             "bj920000": Kind.STOCK}
    session = requests.Session()
    session.trust_env = False
    tencent = session.get("https://qt.gtimg.cn/q=" + ",".join(codes), timeout=10).content.decode("gbk")
    sina = session.get("https://hq.sinajs.cn/list=" + ",".join(codes), timeout=10,
                       headers={"Referer": "https://finance.sina.com.cn"}).content.decode("gbk")
    lots = {line.split("=")[0].split("_")[-1]: float(line.split('"')[1].split("~")[6])
            for line in tencent.split(";") if '"' in line}
    shares = {line.split("=")[0].split("_")[-1]: float(line.split('"')[1].split(",")[8])
              for line in sina.split(";") if '"' in line}
    print("== 腾讯报价成交量单位核对（新浪成交量[股] ÷ 腾讯成交量；科创板预期 1，其他板块预期 100）")
    all_ok = True
    for key, kind in codes.items():
        sec = parse(key, kind)
        assert to_source_code(sec, "tencent") == key
        expected = 1 if sec.board is Board.STAR else SHARES_PER_LOT
        ratio = shares[key] / lots[key] if lots.get(key) else None
        good = ratio is not None and abs(ratio - expected) / expected < 0.01
        all_ok &= good
        print(f"  {sec} 板块={sec.board} 腾讯={lots.get(key)} 新浪={shares.get(key)} 比值={ratio} "
              f"预期={expected} {'OK' if good else '不符'}")
    return all_ok


if __name__ == "__main__":
    results = [check_rule_table(), check_lot_size()]
    sys.exit(0 if all(results) else 1)
