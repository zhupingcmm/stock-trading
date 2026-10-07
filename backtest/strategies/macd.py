"""MACD 策略 — 趋势跟踪。

DIF 上穿 DEA（金叉）→ 买入；DIF 下穿 DEA（死叉）→ 卖出。
参数：短 12 / 长 26 / 信号线 9。
"""
from __future__ import annotations

import backtrader as bt


STRATEGY_META = {
    "name": "MACD策略",
    "category": "trend",
    "desc": "DIF/DEA 金叉死叉",
    "params": {"short": 12, "long": 26, "signal": 9},
    "logic": "DIF 上穿 DEA(金叉) → 买入; DIF 下穿 DEA(死叉) → 卖出",
}


class Strategy(bt.Strategy):
    params = (("short", 12), ("long", 26), ("signal", 9))

    def __init__(self):
        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.short,
            period_me2=self.p.long,
            period_signal=self.p.signal,
        )
        self.crossover = bt.indicators.CrossOver(self.macd.macd, self.macd.signal)

    def next(self):
        if not self.position:
            if self.crossover[0] > 0:
                self.buy()
        elif self.crossover[0] < 0:
            self.close()
