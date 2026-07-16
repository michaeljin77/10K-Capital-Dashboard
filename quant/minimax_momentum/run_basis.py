#!/usr/bin/env python3
"""M-BASIS perp–正股 basis 扫描 (STRATEGY.md §5)。

扫描:        python run_basis.py                  # 正股参考价取 yfinance 最近收盘
指定参考价:  python run_basis.py --spot 588.0     # 盘中用现价、竞价窗口用 IEP
核实 coin:   python run_basis.py --check          # 列出 Hyperliquid universe
"""
import argparse

from engine import basis, data
from engine.config import load_config, resolve


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spot", type=float, help="正股参考公允价（默认取最近收盘）")
    ap.add_argument("--check", action="store_true",
                    help="列出 Hyperliquid perp universe，核实 config 里的 coin 名")
    args = ap.parse_args()

    cfg = load_config()
    if args.check:
        names = data.list_perp_universe(cfg["instrument"]["hyperliquid_api"])
        target = cfg["instrument"]["perp_coin"].upper()
        print(f"Hyperliquid universe ({len(names)} coins):")
        for n in sorted(names):
            mark = "  ← config perp_coin" if n.upper() == target else ""
            print(f"  {n}{mark}")
        if target not in {n.upper() for n in names}:
            print(f"\n⚠️ config 里的 {cfg['instrument']['perp_coin']} 不在 universe，"
                  f"修正 config.yaml 后再跑扫描")
        return

    snap = basis.scan(cfg, spot_ref=args.spot)
    print(basis.render(snap))
    path = basis.log_snapshot(snap, resolve(cfg, "log_dir"))
    print(f"\n已落日志: {path}")


if __name__ == "__main__":
    main()
