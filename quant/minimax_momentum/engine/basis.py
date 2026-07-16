"""M-BASIS 扫描器：Hyperliquid MINIMAX perp vs 00100.HK 正股 basis (STRATEGY.md §5)。

真套利腿：perp 与正股锚同一终值，|basis| 扣完全部成本仍为正才触发。
每次扫描都落 JSONL —— 触发不触发都记，为 "开盘是否真收敛" 积累样本。
"""
from dataclasses import dataclass, asdict
import json
import os
import time

from . import data


@dataclass
class BasisSnapshot:
    ts: str
    perp_mid: float
    spot_ref: float                  # 正股参考公允价（盘中=现价；盘后=收盘价）
    basis: float                     # perp/spot − 1
    funding_8h: float | None
    open_interest: float | None
    total_cost: float                # 全成本（perp 双边费 + funding 预算 + 港股往返）
    net_edge: float                  # |basis| − total_cost
    triggered: bool
    direction: str | None            # basis>0: SHORT_PERP_LONG_STOCK；反之反向


def scan(cfg: dict, spot_ref: float | None = None) -> BasisSnapshot:
    b = cfg["basis"]
    inst = cfg["instrument"]
    quote = data.fetch_perp_quote(inst["hyperliquid_api"], inst["perp_coin"])
    if spot_ref is None:
        spot_ref = data.fetch_hk_prev_close(inst["hk_ticker"])

    basis = quote.mid / spot_ref - 1
    funding_cost = abs(quote.funding_8h) if quote.funding_8h is not None \
        else b["funding_budget_8h"]
    total_cost = (b["perp_taker_fee"] * 2 + funding_cost
                  + b["hk_round_trip_cost"])
    net_edge = abs(basis) - total_cost
    triggered = abs(basis) >= b["min_abs_basis"] and net_edge > 0

    direction = None
    if triggered:
        direction = "SHORT_PERP_LONG_STOCK" if basis > 0 else "LONG_PERP_SHORT_STOCK"

    return BasisSnapshot(
        ts=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        perp_mid=quote.mid, spot_ref=spot_ref, basis=basis,
        funding_8h=quote.funding_8h, open_interest=quote.open_interest,
        total_cost=total_cost, net_edge=net_edge,
        triggered=triggered, direction=direction)


def log_snapshot(s: BasisSnapshot, log_dir: str) -> str:
    path = os.path.join(log_dir, "mbasis_scans.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
    return path


def render(s: BasisSnapshot) -> str:
    lines = [
        "═══ M-BASIS perp–正股 basis 扫描 ═══",
        f"perp mid      {s.perp_mid:,.2f}",
        f"正股参考价    {s.spot_ref:,.2f}",
        f"basis         {s.basis:+.2%}",
        f"funding(8h)   {s.funding_8h:+.4%}" if s.funding_8h is not None
        else "funding(8h)   n/a (用预算值)",
        f"全成本        {s.total_cost:.2%}",
        f"净 edge       {s.net_edge:+.2%}",
        "",
        (f"🔔 触发: {s.direction} — perp 腿先建，正股腿 09:00–09:14 竞价对冲，"
         f"09:20 后按收敛平仓，10:00 未收敛硬平"
         if s.triggered else "— 未触发（照常落日志，积累收敛样本）"),
    ]
    return "\n".join(lines)
