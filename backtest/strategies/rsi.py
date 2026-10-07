"""RSI 策略 — 超买超卖。

RSI < 30（超卖）→ 买入；RSI > 70（超买）→ 卖出。
"""
from __future__ import annotations

import backtrader as bt


STRATEGY_META = {
    "name": "RSI策略",
    "category": "mean_reversion",
    "desc": "RSI 超卖买入 / 超买卖出",
    "params": {"period": 14, "oversold": 30, "overbought": 70},
    "logic": "RSI<30(超卖) → 买入; RSI>70(超买) → 卖出",
}


class Strategy(bt.Strategy):
    params = (("period", 14), ("oversold", 30), ("overbought", 70))

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.p.period)

    def next(self):
        if not self.position:
            if self.rsi[0] < self.p.oversold:
                self.buy()
        elif self.rsi[0] > self.p.overbought:
            self.close()
