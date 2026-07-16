"""数据适配层：美股篮子 / 港股正股 (yfinance)，Hyperliquid perp (公共 info API)。

任一数据源失败都抛异常而不是静默降级 —— 缺数据出的信号比不出信号更危险。
IEP 没有免费 API，由 run_paper.py 的 --iep 参数人工输入。
"""
from dataclasses import dataclass

import pandas as pd
import requests


# ── 美股篮子 / 港股日线 (yfinance) ──────────────────────────────

def fetch_daily_closes(tickers: list[str], lookback_days: int = 130) -> pd.DataFrame:
    import yfinance as yf
    raw = yf.download(
        tickers, period=f"{lookback_days}d", interval="1d",
        auto_adjust=True, progress=False, group_by="ticker",
    )
    closes = pd.DataFrame({t: raw[t]["Close"] for t in tickers})
    return closes.dropna(how="all")


def basket_overnight_return(closes: pd.DataFrame, weights: dict[str, float]) -> float:
    """篮子最近一个交易日的 close-to-close 加权收益（即港股开盘前的隔夜信号）。"""
    rets = closes.iloc[-1] / closes.iloc[-2] - 1
    return float(sum(rets[t] * w for t, w in weights.items()))


def fetch_hk_prev_close(hk_ticker: str) -> float:
    import yfinance as yf
    hist = yf.Ticker(hk_ticker).history(period="5d", auto_adjust=False)
    if hist.empty:
        raise RuntimeError(f"{hk_ticker}: yfinance 无数据")
    return float(hist["Close"].iloc[-1])


# ── Hyperliquid perp ────────────────────────────────────────────

@dataclass
class PerpQuote:
    coin: str
    mid: float
    funding_8h: float | None
    open_interest: float | None


def fetch_perp_quote(api_url: str, coin: str) -> PerpQuote:
    meta, ctxs = requests.post(
        api_url, json={"type": "metaAndAssetCtxs"}, timeout=10
    ).json()
    for asset, ctx in zip(meta["universe"], ctxs):
        if asset["name"].upper() == coin.upper():
            return PerpQuote(
                coin=asset["name"],
                mid=float(ctx["midPx"]),
                funding_8h=float(ctx["funding"]) if ctx.get("funding") is not None else None,
                open_interest=float(ctx["openInterest"]) if ctx.get("openInterest") is not None else None,
            )
    raise RuntimeError(
        f"Hyperliquid 上找不到 coin={coin}；用 run_basis.py --check 列出可用 universe 核实名称"
    )


def list_perp_universe(api_url: str) -> list[str]:
    meta = requests.post(api_url, json={"type": "meta"}, timeout=10).json()
    return [a["name"] for a in meta["universe"]]
