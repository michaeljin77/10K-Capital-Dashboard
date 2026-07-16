# MiniMax 隔夜情绪 Gap 策略 · 程序使用说明

策略本体见 [STRATEGY.md](STRATEGY.md)。**v0.1 = paper only**，四量验收（Q1 传导比 / Q2 已定价比例 / Q3 衰减 / Q4 黑名单占比）全部 GO 之前不碰真钱。

## 安装

```bash
cd quant/minimax_momentum
pip install -r requirements.txt
```

## 先跑通管线（全合成数据，不访问外部数据源）

```bash
python run_backtest.py --demo     # 四量报告管线
python run_paper.py --demo        # M-DIR 信号决策管线
```

## 日常流程（HKT，美东夏令时）

| 时刻 | 命令 | 说明 |
|---|---|---|
| 08:30–08:50 | `python run_paper.py` | 黑名单 + 信号强度 + perp 价预检已定价比例 |
| 09:05–09:14 | `python run_paper.py --stage iep_final --iep <行情终端读到的IEP>` | IEP 终检，两次都过才（paper）挂单 |
| 收盘后 | 往 `data/history.csv` 追加当日一行 | 列定义见 `engine/backtest.py` 顶部注释 |
| 每周 | `python run_backtest.py --csv data/history.csv --json` | 四量滚动复核 |
| 任意时刻 | `python run_basis.py` / `--spot <现价或IEP>` | M-BASIS 扫描（不触发也落日志，积累收敛样本） |
| 首次使用前 | `python run_basis.py --check` | 核实 Hyperliquid 上 MINIMAX 的 coin 名 |

cron 示例（服务器为 UTC，HKT = UTC+8）：

```cron
30 0 * * 1-5  cd /path/to/quant/minimax_momentum && python run_paper.py >> logs/cron.log 2>&1
0  * * * *    cd /path/to/quant/minimax_momentum && python run_basis.py >> logs/cron.log 2>&1
```

（IEP 终检没法 cron——IEP 无免费 API，必须人工从行情终端读数后手动跑。）

## 黑名单维护（第一道闸）

编辑 `blacklist.yaml`。解禁 / 财报 / 投行评级密集 / 模型发布 / 指数调整全拉黑。
**事后发现漏录 = 事故**：补日历 + 当周停跑（STRATEGY.md §6.3）。

## 日志

全部 JSONL 追加写在 `logs/`：

- `mdir_decisions.jsonl` — 每次信号决策（TRADE 与拒单原因同等重要）
- `mbasis_scans.jsonl` — 每次 basis 扫描快照
- `four_quant_report.json` — 最近一次四量报告

## 文件结构

```
STRATEGY.md          策略文档 v0.1（触发条件表 + 执行时刻表 + 四量验收线）
config.yaml          全部阈值（只能收紧不能放宽）
blacklist.yaml       catalyst 黑名单
engine/
  signals.py         M-DIR 触发条件表逐条实现 + 已定价比例
  backtest.py        四量回测引擎 + go/no-go 判定
  basis.py           M-BASIS 扫描器（全成本净 edge）
  data.py            yfinance + Hyperliquid 数据适配
  blacklist.py       黑名单检查
run_paper.py         每日信号 CLI（perp 预检 / IEP 终检两段式）
run_backtest.py      四量回测 CLI
run_basis.py         basis 扫描 CLI
```
