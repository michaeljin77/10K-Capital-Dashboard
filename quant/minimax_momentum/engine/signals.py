"""M-DIR 信号引擎：触发条件表 (STRATEGY.md §3) 的逐条实现。

条件按顺序短路评估，任一失败即拒单并给出拒单原因 —— 拒单原因和成交信号
同等重要，全部落 JSONL 供四量回测复核。
"""
from dataclasses import dataclass, field, asdict
from datetime import date as Date
import json
import os
import time

import numpy as np

from . import blacklist as bl


@dataclass
class BetaEstimate:
    beta: float
    tstat: float
    n_clean_days: int


@dataclass
class Decision:
    date: str
    stage: str                       # "perp_precheck" (08:50) | "iep_final" (09:0x)
    action: str                      # "TRADE" | "NO_TRADE"
    reject_reason: str | None = None
    direction: str | None = None     # "LONG" | "SHORT"
    basket_ret: float | None = None
    beta: float | None = None
    expected_gap: float | None = None
    ref_price: float | None = None
    prev_close: float | None = None
    priced_in: float | None = None
    venue: str | None = None         # "HK_AUCTION" | "PERP"
    notional_usd: float | None = None
    soft_stop: float | None = None
    hard_stop: float | None = None
    hard_flat_hkt: str | None = None
    notes: list[str] = field(default_factory=list)


def rolling_beta(basket_rets: np.ndarray, gaps: np.ndarray,
                 clean_mask: np.ndarray) -> BetaEstimate:
    """干净日上 gap 对篮子隔夜收益的 OLS（过原点：信号为零时不应有系统性 gap）。"""
    x = basket_rets[clean_mask]
    y = gaps[clean_mask]
    n = len(x)
    if n < 3 or float(x @ x) == 0.0:
        return BetaEstimate(beta=0.0, tstat=0.0, n_clean_days=n)
    beta = float(x @ y) / float(x @ x)
    resid = y - beta * x
    se = float(np.sqrt((resid @ resid) / (n - 1) / (x @ x)))
    tstat = beta / se if se > 0 else 0.0
    return BetaEstimate(beta=beta, tstat=tstat, n_clean_days=n)


def priced_in_ratio(ref_price: float, prev_close: float, expected_gap: float) -> float:
    """已定价比例 = 参考价已走出的 gap / 预期 gap。

    同向时 ∈ [0, +∞)；参考价与预期反向时为负（负值 = 完全未定价，甚至给出
    更好的进场价，不拒单）。expected_gap 为 0 时无意义，调用方先挡掉。
    """
    realized = ref_price / prev_close - 1
    return realized / expected_gap


def decide(*, day: Date, stage: str, basket_ret: float, beta_est: BetaEstimate,
           prev_close: float, ref_price: float, cfg: dict,
           blacklist_entries: list[dict] | None = None) -> Decision:
    sig = cfg["signal"]
    risk = cfg["risk"]
    d = Decision(date=day.isoformat(), stage=stage, action="NO_TRADE",
                 basket_ret=basket_ret, beta=beta_est.beta,
                 prev_close=prev_close, ref_price=ref_price)

    # 1. 黑名单
    hit = bl.check(day, blacklist_entries)
    if hit:
        d.reject_reason = f"blacklist:{hit.category}"
        d.notes.append(hit.note)
        return d

    # 2. 篮子信号强度
    if abs(basket_ret) < sig["min_abs_basket_ret"]:
        d.reject_reason = (f"weak_signal:|{basket_ret:.4f}|"
                           f"<{sig['min_abs_basket_ret']}")
        return d

    # 3. 传导比有效性
    if beta_est.n_clean_days < sig["min_clean_days"]:
        d.reject_reason = f"beta_sample:{beta_est.n_clean_days}<{sig['min_clean_days']}"
        return d
    if beta_est.beta < sig["min_beta"] or beta_est.tstat < sig["min_beta_tstat"]:
        d.reject_reason = (f"beta_invalid:beta={beta_est.beta:.3f},"
                           f"t={beta_est.tstat:.2f}")
        return d

    # 4. 已定价比例
    expected_gap = beta_est.beta * basket_ret
    d.expected_gap = expected_gap
    ratio = priced_in_ratio(ref_price, prev_close, expected_gap)
    d.priced_in = ratio
    if ratio >= sig["max_priced_in"]:
        d.reject_reason = f"priced_in:{ratio:.0%}>={sig['max_priced_in']:.0%}"
        return d

    # 5. 方向与执行场所：空单走 perp 绕开 tick rule/券源，正股只做多
    d.direction = "LONG" if expected_gap > 0 else "SHORT"
    d.venue = "HK_AUCTION" if d.direction == "LONG" else "PERP"

    # 6. 仓位与风控参数（paper 固定名义）
    d.action = "TRADE"
    d.notional_usd = risk["paper_notional_usd"]
    d.soft_stop = risk["soft_stop"]
    d.hard_stop = risk["hard_stop"]
    d.hard_flat_hkt = risk["hard_flat_hkt"]
    if stage == "perp_precheck":
        d.notes.append("预检通过 ≠ 出单：09:05–09:14 必须用 IEP 复核已定价比例")
    return d


def log_decision(d: Decision, log_dir: str) -> str:
    path = os.path.join(log_dir, "mdir_decisions.jsonl")
    rec = asdict(d) | {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path
