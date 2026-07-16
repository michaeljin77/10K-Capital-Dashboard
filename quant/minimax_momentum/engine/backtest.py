"""四量回测引擎 (STRATEGY.md §2)：Q1 传导比 / Q2 已定价比例 / Q3 衰减 / Q4 黑名单占比。

输入 CSV（人工/脚本积累，逐日一行）：
  date, basket_ret, prev_close, ref_price, open, p15, p30, p60, close
  - basket_ret : 美股篮子隔夜加权收益（小数）
  - ref_price  : 进场参考价（08:50 perp 或竞价 IEP，用哪个记哪个并保持一致）
  - open/p15/p30/p60/close : 开盘价及开盘后 15/30/60 分钟价、收盘价
  - p15/p30/p60 允许缺（上市初期拿不到分钟线），对应衰减格输出 NaN

输出四量报告 + 逐条 go/no-go 判定。任一 no-go → M-DIR kill（§2 尾注）。
"""
from dataclasses import dataclass, asdict
from datetime import date as Date
import json

import numpy as np
import pandas as pd

from . import blacklist as bl
from .signals import rolling_beta, BetaEstimate


@dataclass
class FourQuantReport:
    n_days: int
    # Q4 黑名单占比
    n_blacklisted: int
    blacklist_pct: float
    n_clean: int
    n_clean_signal_days: int          # 干净 且 |basket_ret| ≥ 阈值
    q4_go: bool
    # Q1 传导比
    beta: float
    beta_tstat: float
    direction_agreement: float        # 干净信号日方向一致率
    q1_go: bool
    # Q2 已定价比例
    priced_in_median: float
    priced_in_ge50_pct: float
    q2_go: bool
    # Q3 衰减（干净信号日、顺预期方向的平均累计收益，单位 %）
    decay_gap_pct: float
    decay_15m_pct: float
    decay_30m_pct: float
    decay_60m_pct: float
    q3_go: bool
    verdict: str                      # "GO" | "KILL"


def run(df: pd.DataFrame, cfg: dict,
        blacklist_entries: list[dict] | None = None) -> FourQuantReport:
    sig = cfg["signal"]
    if blacklist_entries is None:
        blacklist_entries = bl.load_blacklist()

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["blacklisted"] = df["date"].map(
        lambda d: bl.check(d, blacklist_entries) is not None)
    df["gap"] = df["open"] / df["prev_close"] - 1
    df["signal"] = df["basket_ret"].abs() >= sig["min_abs_basket_ret"]

    clean = ~df["blacklisted"]
    clean_sig = clean & df["signal"]
    n = len(df)

    # ── Q4 黑名单占比 ──
    n_black = int(df["blacklisted"].sum())
    blacklist_pct = n_black / n if n else 0.0
    n_clean_sig = int(clean_sig.sum())
    q4_go = n_clean_sig >= 30 and blacklist_pct <= 0.70

    # ── Q1 传导比 ──
    est: BetaEstimate = rolling_beta(
        df["basket_ret"].to_numpy(float), df["gap"].to_numpy(float),
        clean_sig.to_numpy())
    if n_clean_sig > 0:
        agree = float((np.sign(df.loc[clean_sig, "gap"])
                       == np.sign(df.loc[clean_sig, "basket_ret"])).mean())
    else:
        agree = float("nan")
    q1_go = (est.beta >= sig["min_beta"] and est.tstat >= sig["min_beta_tstat"]
             and not np.isnan(agree) and agree >= 0.60)

    # ── Q2 已定价比例 ──
    sub = df.loc[clean_sig & (est.beta * df["basket_ret"] != 0)].copy()
    if len(sub) and est.beta != 0:
        sub["priced_in"] = ((sub["ref_price"] / sub["prev_close"] - 1)
                            / (est.beta * sub["basket_ret"]))
        pi_median = float(sub["priced_in"].median())
        pi_ge50 = float((sub["priced_in"] >= sig["max_priced_in"]).mean())
    else:
        pi_median, pi_ge50 = float("nan"), float("nan")
    q2_go = not np.isnan(pi_median) and pi_median < sig["max_priced_in"]

    # ── Q3 衰减：顺预期方向 (sign(basket_ret)) 的累计收益 ──
    def leg(col: str) -> float:
        if col not in df.columns:
            return float("nan")
        s = df.loc[clean_sig].dropna(subset=[col])
        if s.empty:
            return float("nan")
        r = (s[col] / s["prev_close"] - 1) * np.sign(s["basket_ret"])
        return float(r.mean() * 100)

    d_gap, d15, d30, d60 = leg("open"), leg("p15"), leg("p30"), leg("p60")
    # 成本下限：印花税+佣金+滑点（config basis.hk_round_trip_cost 复用为成本基准）
    cost_pct = cfg["basis"]["hk_round_trip_cost"] * 100
    q3_go = (not np.isnan(d15) and not np.isnan(d30)
             and d15 > cost_pct and d30 > cost_pct)

    verdict = "GO" if (q1_go and q2_go and q3_go and q4_go) else "KILL"
    return FourQuantReport(
        n_days=n, n_blacklisted=n_black, blacklist_pct=blacklist_pct,
        n_clean=int(clean.sum()), n_clean_signal_days=n_clean_sig, q4_go=q4_go,
        beta=est.beta, beta_tstat=est.tstat, direction_agreement=agree, q1_go=q1_go,
        priced_in_median=pi_median, priced_in_ge50_pct=pi_ge50, q2_go=q2_go,
        decay_gap_pct=d_gap, decay_15m_pct=d15, decay_30m_pct=d30,
        decay_60m_pct=d60, q3_go=q3_go, verdict=verdict)


def render(r: FourQuantReport) -> str:
    def mark(ok: bool) -> str:
        return "GO ✅" if ok else "NO-GO ❌"
    lines = [
        "═══ MiniMax M-DIR 四量回测报告 ═══",
        f"样本: {r.n_days} 交易日 | 黑名单 {r.n_blacklisted} 天 ({r.blacklist_pct:.0%})"
        f" | 干净信号日 {r.n_clean_signal_days}",
        "",
        f"Q1 传导比      beta={r.beta:.3f} t={r.beta_tstat:.2f}"
        f" 方向一致率={r.direction_agreement:.0%}   → {mark(r.q1_go)}",
        f"Q2 已定价比例  中位数={r.priced_in_median:.0%}"
        f" ≥50%占比={r.priced_in_ge50_pct:.0%}   → {mark(r.q2_go)}",
        f"Q3 衰减        gap={r.decay_gap_pct:+.2f}% +15m={r.decay_15m_pct:+.2f}%"
        f" +30m={r.decay_30m_pct:+.2f}% +60m={r.decay_60m_pct:+.2f}%   → {mark(r.q3_go)}",
        f"Q4 干净信号日  {r.n_clean_signal_days} 天 (需≥30)"
        f" 黑名单占比 {r.blacklist_pct:.0%} (需≤70%)   → {mark(r.q4_go)}",
        "",
        f"结论: {'✅ GO — 可进入 paper 实测' if r.verdict == 'GO' else '❌ KILL — 不降标准；考虑换恒生科技或 AI 篮子载体'}",
    ]
    return "\n".join(lines)


def to_json(r: FourQuantReport) -> str:
    return json.dumps(asdict(r), ensure_ascii=False, indent=2)


# ── demo 数据：让引擎无真实数据也能端到端跑通 ──────────────────

def synthetic_demo(cfg: dict, n_days: int = 90, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=Date.today(), periods=n_days).date
    basket = rng.normal(0, 0.02, n_days)
    true_beta = 0.55
    idio = rng.normal(0, 0.06, n_days)          # MiniMax 级别的个股噪声
    gap = true_beta * basket + idio
    prev_close = 600 * np.exp(np.cumsum(rng.normal(0, 0.05, n_days)))
    open_ = prev_close * (1 + gap)
    priced = rng.uniform(0.1, 0.9, n_days)      # 已定价比例分布
    ref = prev_close * (1 + priced * true_beta * basket)
    decay = rng.uniform(0.3, 1.1, (n_days, 3))  # 开盘后回吐系数
    return pd.DataFrame({
        "date": dates, "basket_ret": basket, "prev_close": prev_close,
        "ref_price": ref, "open": open_,
        "p15": prev_close * (1 + gap * decay[:, 0]),
        "p30": prev_close * (1 + gap * decay[:, 1]),
        "p60": prev_close * (1 + gap * decay[:, 2]),
        "close": prev_close * (1 + gap * rng.uniform(0.0, 1.2, n_days)),
    })
