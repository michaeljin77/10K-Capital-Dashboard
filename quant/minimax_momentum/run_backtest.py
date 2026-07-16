#!/usr/bin/env python3
"""四量回测 (STRATEGY.md §2)。

真实数据:  python run_backtest.py --csv data/history.csv
合成演练:  python run_backtest.py --demo   (验证管线，结论无意义)
"""
import argparse
import os

import pandas as pd

from engine import backtest
from engine.config import load_config, resolve


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", help="历史数据 CSV，列定义见 engine/backtest.py 顶部注释")
    ap.add_argument("--demo", action="store_true", help="合成数据演练")
    ap.add_argument("--json", action="store_true", help="额外输出 JSON 报告")
    args = ap.parse_args()

    cfg = load_config()
    if args.demo:
        df = backtest.synthetic_demo(cfg)
        print("[demo] 合成数据 —— 只验证管线，四量结论无意义\n")
    elif args.csv:
        df = pd.read_csv(args.csv)
    else:
        ap.error("需要 --csv 或 --demo")

    report = backtest.run(df, cfg)
    print(backtest.render(report))

    if args.json:
        out = os.path.join(resolve(cfg, "log_dir"), "four_quant_report.json")
        with open(out, "w", encoding="utf-8") as f:
            f.write(backtest.to_json(report))
        print(f"\nJSON 报告: {out}")


if __name__ == "__main__":
    main()
