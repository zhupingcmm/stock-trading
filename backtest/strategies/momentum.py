"""动量策略 — 动量因子。

N 日涨幅 > 5% → 买入；N 日跌幅 > 5% → 卖出。
"""
from __future__ import annotations

import backtrader as bt


STRATEGY_META = {
    "name": "动量策略",
    "category": "momentum",
    "desc": "N 日涨幅超阈值买入 / 跌幅超阈值卖出",
    "params": {"period": 20, "threshold": 5.0},
    "logic": "N日涨幅>5% → 买入; N日跌幅<-5% → 卖出",
}


class Strategy(bt.Strategy):
    params = (("period", 20), ("threshold", 5.0))

    def __init__(self):
        # ROC100: 百分比形式的变动率 (Rate of Change)
        self.roc = bt.indicators.ROC100(self.data.close, period=self.p.period)

    def next(self):
        if not self.position:
            if self.roc[0] > self.p.threshold:
                self.buy()
        elif self.roc[0] < -self.p.threshold:
            self.close()
