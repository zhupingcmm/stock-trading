"""乖离率策略 — 均值回归。

``BIAS = (close - MA20) / MA20 * 100``

BIAS < -6%（超跌）→ 买入；BIAS > 3%（超涨）→ 卖出。
（卖出阈值采用案例代码 3%，不是 6%；买入 -6% 与卖出 3% 形成非对称区间）
"""
from __future__ import annotations

import backtrader as bt


STRATEGY_META = {
    "name": "乖离率策略",
    "category": "mean_reversion",
    "desc": "价格相对均线偏离超跌买入 / 超涨卖出",
    "params": {"period": 20, "buy_threshold": -6.0, "sell_threshold": 3.0},
    "logic": "BIAS<-6% → 买入; BIAS>3% → 卖出",
}


class Strategy(bt.Strategy):
    params = (("period", 20), ("buy_threshold", -6.0), ("sell_threshold", 3.0))

    def __init__(self):
        self.sma = bt.indicators.SMA(self.data.close, period=self.p.period)

    def next(self):
        bias = (self.data.close[0] - self.sma[0]) / self.sma[0] * 100
        if not self.position:
            if bias < self.p.buy_threshold:
                self.buy()
        elif bias > self.p.sell_threshold:
            self.close()
