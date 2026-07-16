"""Catalyst 黑名单 — 策略第一道闸（STRATEGY.md §3 条件 1）。"""
from dataclasses import dataclass
from datetime import date as Date
import os

import yaml

from .config import STRATEGY_DIR


@dataclass
class BlacklistHit:
    category: str
    note: str


def load_blacklist(path: str | None = None) -> list[dict]:
    path = path or os.path.join(STRATEGY_DIR, "blacklist.yaml")
    with open(path, "r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc.get("entries") or []


def check(day: Date, entries: list[dict] | None = None) -> BlacklistHit | None:
    """命中返回 BlacklistHit（含类别与说明），未命中返回 None。"""
    if entries is None:
        entries = load_blacklist()
    for e in entries:
        if "date" in e:
            if _as_date(e["date"]) == day:
                return BlacklistHit(e.get("category", "other"), e.get("note", ""))
        elif "start" in e and "end" in e:
            if _as_date(e["start"]) <= day <= _as_date(e["end"]):
                return BlacklistHit(e.get("category", "other"), e.get("note", ""))
    return None


def _as_date(v) -> Date:
    if isinstance(v, Date):
        return v
    return Date.fromisoformat(str(v))
