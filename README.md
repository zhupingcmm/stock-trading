# Stock Trading

一个面向 A 股的量化投研项目，覆盖 **数据采集 → 选股 → 回测** 三个核心环节。

## 目录结构

```text
stock-trading/
├── data_collection/        # 数据采集
│   ├── sources/            # 数据源（akshare / tushare / wind 等适配）
│   ├── collectors/         # 采集器（按数据类型：行情、财务、公告...）
│   ├── storage/            # 存储层（csv / parquet / 数据库）
│   └── schedulers/         # 定时任务（每日/分钟级增量更新）
├── selection/              # 选股
│   ├── factors/            # 因子库（基本面、技术、量价...）
│   ├── strategies/         # 选股策略（多因子、事件驱动...）
│   ├── filters/            # 过滤器（停牌、ST、流动性...）
│   └── ranking/            # 打分与排序
├── backtest/               # 回测（基于 backtrader）
│   ├── engine/             # 引擎：data 加载 / wrapper 包装 / cerebro 配置 / metrics 计算
│   │   ├── data.py         #   从 trade_stock_daily 加载 K 线
│   │   ├── wrapper.py      #   自动记录交易与净值
│   │   ├── cerebro.py      #   资金/手续费/仓位 + 3 个分析器
│   │   └── metrics.py      #   收益/回撤/夏普/卡玛/盈亏比/利润因子
│   ├── strategies/         # 策略
│   │   ├── double_ma.py    #   双均线 V4（ATR止损 + ADX过滤 + 分批建仓）
│   │   ├── macd.py         #   MACD 金叉死叉
│   │   ├── rsi.py          #   RSI 超买超卖
│   │   ├── boll.py         #   布林带
│   │   ├── bias.py         #   乖离率
│   │   ├── momentum.py     #   动量
│   │   └── custom/         #   用户自定义插件（自动加载）
│   ├── reports/            # 报告输出
│   │   ├── printer.py      #   控制台指标 + 多策略汇总表
│   │   └── plotter.py      #   三联图（K线+买卖点 / 净值 / 回撤）
│   └── portfolio/          # 组合构建与调仓（待实现）
├── config/                 # 全局配置
├── scripts/                # 命令行脚本入口
├── notebooks/              # Jupyter 探索
├── tests/                  # 单元测试与 fixture
└── docs/                   # 项目文档
```

## 快速开始

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

## 数据采集

数据全部通过 `data_collection/collectors/*` 一次性写入 MySQL。  
**关键约束：选股阶段只读 MySQL，不再访问 QMT。** 任何 QMT 调用都集中
在数据采集阶段（`data_collection/sources/xtquant.py`），由 collector 包装。

可用的采集 CLI（在 Windows + MiniQMT 环境下运行）：

```bash
python -m scripts.run_stock_meta    # 股票名 + 申万行业（写入 trade_stock_meta）
python -m scripts.run_daily_quote   # 日线行情
python -m scripts.run_financial     # 财务报表
python -m scripts.run_macro         # 宏观经济
python -m scripts.run_news          # 个股新闻
python -m scripts.run_report        # 研报数据
python -m scripts.run_calendar      # 财经日历
python -m scripts.run_catalyst      # 关键催化剂（依赖 Qwen Max API）
```

各 CLI 支持 `--mode test|full` 与 `--workers N`，先用 `test` 模式验证。

## 选股

```bash
python -m scripts.run_selection_industry  # 多因子行业版选股
```

数据流：`trade_stock_financial` + `trade_stock_meta` → `FinancialFactorComputer`
→ `IndustryScoreRanker` → `ScoreThresholdFilter` → CSV + 可视化。

## 回测

```bash
# 跑全部内置策略 + 自定义插件
python -m scripts.run_backtest

# 只跑某个策略
python -m scripts.run_backtest --strategy macd

# 换标的 / 时间窗口
python -m scripts.run_backtest --stock 600519.SH --start 2025-01-01 --end 2025-12-31

# 跳过 PNG 提速
python -m scripts.run_backtest --no-plot

# 列出所有可用策略 key
python -m scripts.run_backtest --list

# 加载额外自定义策略目录
python -m scripts.run_backtest --strategy-dir D:/my/strategies
```

### 内置策略一览

| key | 类别 | 信号 |
|---|---|---|
| `double_ma` | 趋势 | 快10上穿慢30 + ADX≥18；ATR跟踪止损 / 死叉 / 持仓>60天 卖出 |
| `macd` | 趋势 | DIF上穿DEA买入；DIF下穿DEA卖出 |
| `rsi` | 均值回归 | RSI<30 买入；RSI>70 卖出 |
| `boll` | 波动率 | 收盘<下轨买入；收盘>上轨卖出 |
| `bias` | 均值回归 | BIAS<-6% 买入；BIAS>3% 卖出 |
| `momentum` | 动量 | 20日涨幅>5% 买入；20日跌幅<-5% 卖出 |

### 加自定义策略

把 `.py` 丢到 `backtest/strategies/custom/`，遵守约定即可被自动发现：

```python
import backtrader as bt

STRATEGY_META = {
    "name": "我的策略",
    "category": "custom",
    "desc": "...",
    "params": {...},
    "logic": "...",
}

class Strategy(bt.Strategy):
    params = (...)
    def __init__(self): ...
    def next(self): ...
```

文件名（去 `.py`）即 `--strategy` 的 key。

### 输出

- **控制台**：单策略两行指标 + 多策略汇总表（含最佳/最差高亮）
- **图表**：三联图（K线+买卖点 / 净值曲线 vs 基准 / 回撤），保存到 `DATA_ROOT/backtest/`

## 模块说明

- **data_collection**：统一封装行情、财务、指数等数据源，提供本地落盘与增量更新能力。
- **selection**：基于因子库构建选股策略，通过过滤器剔除不可交易标的，最终输出排序后的股票池。
- **backtest**：基于 backtrader + 历史数据驱动的回测引擎，输出收益曲线、最大回撤、Sharpe、卡玛、盈亏比、利润因子等指标；策略以插件方式组织（内置 6 个 + `custom/` 自动加载）。

## 路线图

- [x] 回测引擎：backtrader 集成 + 6 个内置策略 + 自定义插件机制
- [x] 报告：PNG 三联图（K线+买卖点 / 净值 / 回撤）+ 控制台汇总表
- [ ] 数据采集：akshare / tushare 适配
- [ ] 因子库：基础技术面与基本面因子
- [ ] 多股票组合回测（`backtest/portfolio/`）
- [ ] 报告：HTML 输出