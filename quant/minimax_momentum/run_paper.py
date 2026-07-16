#!/usr/bin/env python3
"""M-DIR paper trading 信号生成 (执行时刻表见 STRATEGY.md §4)。

08:30/08:50 HKT 预检（perp 价做参考价）:
    python run_paper.py
09:05–09:14 HKT 终检（人工输入行情终端的竞价 IEP）:
    python run_paper.py --stage iep_final --iep 585.0

beta 来源：优先读 data/history.csv 上的干净日回归；无历史数据时必须显式
传 --beta/--beta-tstat/--beta-n（例如来自离线回测），否则按样本不足拒单。
"""
import argparse
from datetime import date

import pandas as pd

from engine import data, signals
from engine.backtest import synthetic_demo
from engine.config import load_config, resolve
from engine.signals import BetaEstimate, rolling_beta
import engine.blacklist as bl
import numpy as np
import os


def estimate_beta_from_history(cfg: dict, data_dir: str) -> BetaEstimate | None:
    path = os.path.join(data_dir, "history.csv")
    if not os.path.exists(path):
        return None
    df = pd.read_csv(path).tail(cfg["signal"]["beta_window"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    entries = bl.load_blacklist()
    clean = df["date"].map(lambda d: bl.check(d, entries) is None).to_numpy()
    sig = (df["basket_ret"].abs() >= cfg["signal"]["min_abs_basket_ret"]).to_numpy()
    gaps = (df["open"] / df["prev_close"] - 1).to_numpy(float)
    return rolling_beta(df["basket_ret"].to_numpy(float), gaps, clean & sig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["perp_precheck", "iep_final"],
                    default="perp_precheck")
    ap.add_argument("--iep", type=float,
                    help="竞价 IEP（stage=iep_final 时必填，行情终端人工读取）")
    ap.add_argument("--date", default=None, help="覆盖信号日期 YYYY-MM-DD（回放用）")
    ap.add_argument("--beta", type=float, help="离线回测得到的 beta")
    ap.add_argument("--beta-tstat", type=float, default=0.0)
    ap.add_argument("--beta-n", type=int, default=0, help="beta 的干净样本数")
    ap.add_argument("--demo", action="store_true",
                    help="全合成数据端到端演练，不访问任何外部数据源")
    args = ap.parse_args()

    cfg = load_config()
    log_dir = resolve(cfg, "log_dir")
    data_dir = resolve(cfg, "data_dir")
    day = date.fromisoformat(args.date) if args.date else date.today()

    if args.demo:
        hist = synthetic_demo(cfg)
        basket_ret = float(hist["basket_ret"].iloc[-1])
        prev_close = float(hist["prev_close"].iloc[-1])
        ref_price = float(hist["ref_price"].iloc[-1])
        entries = bl.load_blacklist()
        clean = hist["date"].map(lambda d: bl.check(d, entries) is None).to_numpy()
        sig_mask = (hist["basket_ret"].abs()
                    >= cfg["signal"]["min_abs_basket_ret"]).to_numpy()
        gaps = (hist["open"] / hist["prev_close"] - 1).to_numpy(float)
        beta_est = rolling_beta(hist["basket_ret"].to_numpy(float), gaps,
                                clean & sig_mask)
        print("[demo] 合成数据演练，不代表任何真实信号\n")
    else:
        tickers = list(cfg["basket"].keys())
        closes = data.fetch_daily_closes(tickers)
        basket_ret = data.basket_overnight_return(closes, cfg["basket"])
        prev_close = data.fetch_hk_prev_close(cfg["instrument"]["hk_ticker"])
        if args.stage == "iep_final":
            if args.iep is None:
                ap.error("--stage iep_final 需要 --iep（竞价参考平衡价）")
            ref_price = args.iep
        else:
            quote = data.fetch_perp_quote(cfg["instrument"]["hyperliquid_api"],
                                          cfg["instrument"]["perp_coin"])
            ref_price = quote.mid
        if args.beta is not None:
            beta_est = BetaEstimate(args.beta, args.beta_tstat, args.beta_n)
        else:
            beta_est = estimate_beta_from_history(cfg, data_dir) or \
                BetaEstimate(0.0, 0.0, 0)

    d = signals.decide(day=day, stage=args.stage, basket_ret=basket_ret,
                       beta_est=beta_est, prev_close=prev_close,
                       ref_price=ref_price, cfg=cfg)
    path = signals.log_decision(d, log_dir)

    print(f"═══ M-DIR {d.stage} · {d.date} ═══")
    print(f"篮子隔夜收益  {basket_ret:+.2%}")
    print(f"beta          {beta_est.beta:.3f} (t={beta_est.tstat:.2f}, "
          f"n={beta_est.n_clean_days})")
    if d.expected_gap is not None:
        print(f"预期 gap      {d.expected_gap:+.2%}")
        print(f"参考价/前收   {ref_price:,.2f} / {prev_close:,.2f} → "
              f"已定价 {d.priced_in:.0%}")
    if d.action == "TRADE":
        print(f"\n✅ TRADE {d.direction} @ {d.venue} · 名义 ${d.notional_usd:,.0f} "
              f"(paper)")
        print(f"   止损 {d.soft_stop:.0%} 减半 / {d.hard_stop:.0%} 全平 · "
              f"{d.hard_flat_hkt} HKT 无条件硬平")
    else:
        print(f"\n⛔ NO_TRADE — {d.reject_reason}")
    for n in d.notes:
        print(f"   note: {n}")
    print(f"\n已落日志: {path}")


if __name__ == "__main__":
    main()
