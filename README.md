# Stock Trading

一个面向 A 股的量化投研项目，覆盖 **数据采集 → 选股 → 回测** 三个核心环节。

## 目录结构

```
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
├── backtest/               # 回测
│   ├── engine/             # 回测引擎（事件驱动 / 向量化）
│   ├── metrics/            # 评估指标（收益、风险、回撤...）
│   ├── portfolio/          # 组合构建与调仓
│   └── reports/            # 报告输出（图表、HTML）
├── config/                 # 全局配置
├── scripts/                # 命令行脚本入口
├── notebooks/              # Jupyter 探索
├── tests/                  # 单元测试与 fixture
└── docs/                   # 项目文档
```

## 快速开始

> 项目目前仅含骨架，依赖与具体实现会在后续迭代中填充。

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装依赖（待填充）
pip install -r requirements.txt
```

## 模块说明

- **data_collection**：统一封装行情、财务、指数等数据源，提供本地落盘与增量更新能力。
- **selection**：基于因子库构建选股策略，通过过滤器剔除不可交易标的，最终输出排序后的股票池。
- **backtest**：基于历史数据驱动回测引擎，输出收益曲线、最大回撤、Sharpe 等指标。

## 路线图

- [ ] 数据采集：akshare / tushare 适配
- [ ] 因子库：基础技术面与基本面因子
- [ ] 回测引擎：向量化版本
- [ ] 报告：HTML / 图表输出