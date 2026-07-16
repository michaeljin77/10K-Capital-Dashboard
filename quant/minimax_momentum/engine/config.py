"""加载 config.yaml，所有模块共用一个入口。"""
import os
import yaml

STRATEGY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config(path: str | None = None) -> dict:
    path = path or os.path.join(STRATEGY_DIR, "config.yaml")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(cfg: dict, key: str) -> str:
    """paths.* 相对于策略目录解析，并保证目录存在。"""
    p = os.path.join(STRATEGY_DIR, cfg["paths"][key])
    os.makedirs(p, exist_ok=True)
    return p
