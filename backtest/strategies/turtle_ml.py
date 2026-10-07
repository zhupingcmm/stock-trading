"""ML 增强海龟策略 — 用 ML 模型过滤假突破。

来源：CASE-海龟交易法则/4-ML增强海龟策略.py

核心思路
--------
海龟策略最大的问题是假突破：价格突破通道后迅速回落，导致止损。
用机器学习模型预测"这次突破会不会成功"，只在模型看好时入场。

关键设计
--------
1. 多股票训练：用 5-6 只股票的历史突破事件训练模型，提高样本量
2. 时间分割：训练期 vs 测试期（严格避免未来数据泄露）
3. LightGBM / XGBoost / sklearn GBDT：按可用性自动选择
4. 防过拟合：浅树 (max_depth=3) + 正则化 + 最小叶节点数

策略逻辑
--------
与经典海龟完全相同，**仅在入场时增加一道 ML 判断**：
  - 突破信号 → 查询预计算的 ML 预测概率
  - 概率 >= ml_threshold → 入场
  - 概率 < ml_threshold → 跳过

``predictions`` 是 ``{date: probability}`` 字典，必须在回测前由
``backtest.utils.turtle_ml_features.generate_predictions`` 生成。
"""
from __future__ import annotations

import backtrader as bt

from backtest.strategies.turtle_classic import Strategy as ClassicTurtle


STRATEGY_META = {
    "name": "ML 增强海龟策略",
    "category": "trend",
    "desc": "经典海龟 + LightGBM/XGBoost 假突破过滤（外部预训练模型）",
    "requires_predictions": True,
    "params": {
        "entry_period": 20,
        "exit_period": 10,
        "atr_period": 20,
        "risk_pct": 1.0,
        "max_units": 4,
        "add_n": 0.5,
        "stop_n": 2.0,
        "ml_threshold": 0.5,
    },
    "logic": "突破20日最高价 → ML 模型预测概率 >= 阈值 → 入场；"
             "其他规则同经典海龟（ATR 仓位 / 金字塔加仓 / 2N 止损）",
}


class Strategy(ClassicTurtle):
    """ML 增强海龟：在经典海龟基础上叠加 ML 入场过滤。

    必须传 ``predictions={date: probability}`` 字典，否则所有信号都被跳过。
    """

    params = (
        ("entry_period", 20),
        ("exit_period", 10),
        ("atr_period", 20),
        ("risk_pct", 1.0),
        ("max_units", 4),
        ("add_n", 0.5),
        ("stop_n", 2.0),
        ("ml_threshold", 0.5),
        ("predictions", {}),
    )

    def __init__(self):
        super().__init__()
        self.ml_filtered = 0
        self.ml_passed = 0

    def next(self):
        if self.order:
            return
        atr_val = self.atr[0]
        try:
            if atr_val != atr_val:  # NaN
                return
        except TypeError:
            return
        if atr_val <= 0:
            return
        close = self.data.close[0]

        if not self.position:
            # 先满足海龟突破信号
            if close > self.entry_high[-1]:
                current_date = self.data.datetime.date(0)
                prob = self.p.predictions.get(current_date, 0.0)
                if prob >= self.p.ml_threshold:
                    size = self._calc_unit_size()
                    if size > 0:
                        self.order = self.buy(size=size)
                        self.ml_passed += 1
                else:
                    self.ml_filtered += 1
        else:
            # 已持仓：出场 / 加仓完全继承自经典海龟
            if close < self.stop_price:
                self.order = self.close()
                return
            if close < self.exit_low[-1]:
                self.order = self.close()
                return
            if self.units < self.p.max_units:
                if close >= self.last_add_price + self.p.add_n * atr_val:
                    size = self._calc_unit_size()
                    cash = self.broker.getcash()
                    if size > 0 and cash > close * size * 1.01:
                        self.order = self.buy(size=size)

    def stop(self):
        """回测结束时打印 ML 过滤统计。"""
        total = self.ml_passed + self.ml_filtered
        if total > 0:
            print(
                f"  [ML 过滤] 突破信号 {total} | "
                f"通过 {self.ml_passed} ({self.ml_passed / total * 100:.0f}%) | "
                f"过滤 {self.ml_filtered} ({self.ml_filtered / total * 100:.0f}%)"
            )
