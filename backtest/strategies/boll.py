"""布林带策略 — 波动率。

价格触及下轨（均线 - 2σ）→ 买入；触及上轨（均线 + 2σ）→ 卖出。
"""
from __future__ import annotations

import backtrader as bt


STRATEGY_META = {
    "name": "布林带策略",
    "category": "volatility",
    "desc": "收盘价跌破下轨买入，突破上轨卖出",
    "params": {"period": 20, "devfactor": 2.0},
    "logic": "收盘 < 下轨(均线-2σ) → 买入; 收盘 > 上轨(均线+2σ) → 卖出",
}


class Strategy(bt.Strategy):
    params = (("period", 20), ("devfactor", 2.0))

    def __init__(self):
        self.boll = bt.indicators.BollingerBands(
            self.data.close, period=self.p.period, devfactor=self.p.devfactor
        )

    def next(self):
        if not self.position:
            if self.data.close[0] < self.boll.bot[0]:
                self.buy()
        elif self.data.close[0] > self.boll.top[0]:
            self.close()
