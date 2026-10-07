"""经典海龟交易策略 — ATR 仓位管理 + 金字塔加仓 + 2N 止损。

来源：CASE-海龟交易法则/1-经典海龟策略.py

核心理念
--------
海龟交易法则的本质不是"如何发现趋势"，而是"如何科学管理风险"。
四大组件：
  1. 唐奇安通道  — 20 日最高价入场，10 日最低价出场
  2. ATR (N 值)  — 20 日均值，衡量市场波动幅度
  3. ATR 仓位    — 单位大小 = (账户资金 × 1%) / ATR，让价格波动 1 个 ATR
                  时账户恰好变动 risk_pct
  4. 金字塔加仓  — 最多 4 个单位，每上涨 0.5N 加一个单位

适用场景：明确趋势的市场（ETF / 指数 / 强势行业龙头）；
震荡 / 下跌市会产生大量假突破，应配合 ADX 过滤使用（见 turtle_adx）。
"""
from __future__ import annotations

import numpy as np
import backtrader as bt


STRATEGY_META = {
    "name": "经典海龟策略",
    "category": "trend",
    "desc": "唐奇安通道突破 + ATR 仓位管理 + 金字塔加仓 + 2N 止损",
    "params": {
        "entry_period": 20,
        "exit_period": 10,
        "atr_period": 20,
        "risk_pct": 1.0,       # 单笔风险占账户百分比（%）
        "max_units": 4,
        "add_n": 0.5,          # 每上涨 N 个 ATR 加仓
        "stop_n": 2.0,         # 止损 N 个 ATR
    },
    "logic": "突破20日最高价 → ATR 仓位首建1单；每涨0.5N 加仓1单 (≤4)；"
             "跌破止损线 / 10日最低价 → 全部平仓",
}


class Strategy(bt.Strategy):
    """完整海龟交易策略。

    ``risk_pct`` 单位是 %（与原参考脚本一致：1.0 表示 1%）。
    """

    params = (
        ("entry_period", 20),
        ("exit_period", 10),
        ("atr_period", 20),
        ("risk_pct", 1.0),
        ("max_units", 4),
        ("add_n", 0.5),
        ("stop_n", 2.0),
    )

    def __init__(self):
        self.entry_high = bt.ind.Highest(self.data.high, period=self.p.entry_period)
        self.exit_low = bt.ind.Lowest(self.data.low, period=self.p.exit_period)
        self.atr = bt.ind.ATR(self.data, period=self.p.atr_period)

        self.units = 0
        self.entry_prices: list[float] = []
        self.stop_price = 0.0
        self.last_add_price = 0.0
        self.order = None

    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return
        if order.status == order.Completed:
            if order.isbuy():
                fp = order.executed.price
                self.entry_prices.append(fp)
                self.units = len(self.entry_prices)
                self.stop_price = fp - self.p.stop_n * self.atr[0]
                self.last_add_price = fp
            elif order.issell():
                self.units = 0
                self.entry_prices = []
                self.stop_price = 0.0
                self.last_add_price = 0.0
        self.order = None

    def _calc_unit_size(self) -> int:
        """ATR 仓位公式：单位大小 = (账户总值 × 风险比例) / ATR。

        取整到 100 股（A 股 1 手）。
        """
        portfolio_value = self.broker.getvalue()
        atr_val = self.atr[0]
        if atr_val <= 0:
            return 0
        risk_ratio = self.p.risk_pct / 100.0
        unit_size = (portfolio_value * risk_ratio) / atr_val
        unit_size = int(unit_size // 100) * 100
        return max(unit_size, 100)

    def next(self):
        if self.order:
            return
        atr_val = self.atr[0]
        if np.isnan(atr_val) or atr_val <= 0:
            return
        close = self.data.close[0]

        if not self.position:
            # 入场：突破 20 日最高价（前一根），用 ATR 仓位首建 1 单
            if close > self.entry_high[-1]:
                size = self._calc_unit_size()
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 2N 硬止损优先
            if close < self.stop_price:
                self.order = self.close()
                return
            # 唐奇安通道出场
            if close < self.exit_low[-1]:
                self.order = self.close()
                return
            # 金字塔加仓：每上涨 0.5N 加 1 单，最多 4 单
            if self.units < self.p.max_units:
                if close >= self.last_add_price + self.p.add_n * atr_val:
                    size = self._calc_unit_size()
                    cash = self.broker.getcash()
                    if size > 0 and cash > close * size * 1.01:
                        self.order = self.buy(size=size)
