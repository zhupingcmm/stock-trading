"""ADX 趋势过滤海龟策略。

来源：CASE-海龟交易法则/2-ADX海龟策略.py

核心问题
--------
经典海龟策略在震荡市会产生大量假突破，导致频繁止损。

解决方案
--------
用 ADX（平均趋向指数）作为「门卫」：
  - ADX > 阈值 → 市场有趋势 → 允许海龟入场
  - ADX < 阈值 → 市场震荡 → 拒绝入场，避免假突破

ADX 阈值选择
------------
  - 阈值太高（如 25）→ 过滤掉太多信号，包括好的趋势启动
  - 阈值太低（如 10）→ 几乎不过滤，没有效果
  - 实测最佳：15 左右，能过滤最差的假突破，不伤害好信号

已持仓时：出场/加仓逻辑不变，ADX 只影响开仓决策。
"""
from __future__ import annotations

import backtrader as bt

from backtest.strategies.turtle_classic import Strategy as ClassicTurtle


STRATEGY_META = {
    "name": "ADX 过滤海龟策略",
    "category": "trend",
    "desc": "经典海龟 + ADX 趋势强度过滤（ADX > 阈值才入场）",
    "params": {
        "entry_period": 20,
        "exit_period": 10,
        "atr_period": 20,
        "adx_period": 14,
        "adx_threshold": 15,
        "risk_pct": 1.0,
        "max_units": 4,
        "add_n": 0.5,
        "stop_n": 2.0,
    },
    "logic": "ADX(14) > 阈值才允许突破入场；其他规则同经典海龟",
}


class Strategy(ClassicTurtle):
    """ADX 过滤海龟：在经典海龟基础上增加入场 ADX 阈值。

    继承以复用 ATR 仓位 / 金字塔加仓 / 2N 止损 / 出场逻辑。
    """

    params = (
        ("entry_period", 20),
        ("exit_period", 10),
        ("atr_period", 20),
        ("adx_period", 14),
        ("adx_threshold", 15),
        ("risk_pct", 1.0),
        ("max_units", 4),
        ("add_n", 0.5),
        ("stop_n", 2.0),
    )

    def __init__(self):
        super().__init__()
        self.adx = bt.ind.ADX(self.data, period=self.p.adx_period)

    def next(self):
        if self.order:
            return
        atr_val = self.atr[0]
        # ATR 仍需有效（继承自父类 next 也会校验，这里提前判 NaN）
        try:
            if atr_val != atr_val:  # NaN 检测
                return
        except TypeError:
            return
        if atr_val <= 0:
            return
        close = self.data.close[0]

        if not self.position:
            # ADX 门卫：趋势不够强 → 拒绝入场
            if self.adx[0] < self.p.adx_threshold:
                return
            if close > self.entry_high[-1]:
                size = self._calc_unit_size()
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 已持仓：出场 / 加仓逻辑完全继承自经典海龟
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
