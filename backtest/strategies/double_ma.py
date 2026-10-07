"""双均线策略 V4 — 趋势跟踪进阶版（ATR止损 + ADX过滤 + 分批建仓）。

来源：D:\\code\\ai\\quantitative-trading\\CASE-Backtrader回测\\1-双均线策略.py

买入：快线上穿慢线（金叉）且 ADX≥18（趋势有效）
卖出（按优先级）: ATR跟踪止损 / 死叉 / 持仓>60天
加仓：趋势未衰 + 浮盈>3% 时每次加 20%，最多 3 次
"""
from __future__ import annotations

import backtrader as bt


STRATEGY_META = {
    "name": "双均线策略",
    "category": "trend",
    "desc": "快慢均线金叉+ADX趋势过滤，带ATR跟踪止损与分批建仓",
    "params": {
        "fast": 10,
        "slow": 30,
        "atr_period": 14,
        "stop_atr_multi": 1.5,
        "hard_stop_pct": 5.0,
        "adx_period": 14,
        "adx_threshold": 18,
        "initial_pos_pct": 50,
        "add_pos_pct": 20,
        "max_add_times": 3,
    },
    "logic": "金叉+ADX≥18 → 首建50%; 浮盈3%+趋势持续 → 加仓20%(≤3次); "
             "ATR止损/死叉/持仓>60天 → 卖出",
}


class Strategy(bt.Strategy):
    """双均线 V4 — 带止损 + 趋势过滤 + 仓位管理。"""

    params = (
        ("fast", 10),
        ("slow", 30),
        ("atr_period", 14),
        ("stop_atr_multi", 1.5),
        ("hard_stop_pct", 5.0),
        ("use_trailing_stop", True),
        ("adx_period", 14),
        ("adx_threshold", 18),
        ("initial_pos_pct", 50),
        ("add_pos_pct", 20),
        ("max_add_times", 3),
    )

    def __init__(self):
        self.ma_fast = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.ma_slow = bt.indicators.SMA(self.data.close, period=self.p.slow)
        self.crossover = bt.indicators.CrossOver(self.ma_fast, self.ma_slow)
        self.atr = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.adx = bt.indicators.ADX(self.data, period=self.p.adx_period)

        self.entry_price = 0.0
        self.stop_price = 0.0
        self.highest_since_entry = 0.0
        self.entry_date = None
        self.add_count = 0

    def next(self):
        price = self.data.close[0]

        if not self.position:
            adx_ok = self.adx[0] > self.p.adx_threshold
            golden_cross = self.crossover[0] > 0
            if golden_cross and adx_ok:
                cash = self.broker.getcash()
                size = (cash * self.p.initial_pos_pct / 100) / price
                self.buy(size=size)

                atr_stop = price - self.atr[0] * self.p.stop_atr_multi
                hard_stop = price * (1 - self.p.hard_stop_pct / 100)
                self.stop_price = max(atr_stop, hard_stop)

                self.entry_price = price
                self.highest_since_entry = price
                self.entry_date = self.data.datetime.date(0)
                self.add_count = 0
            return

        # 持仓中：跟踪止损
        self.highest_since_entry = max(self.highest_since_entry, price)
        if self.p.use_trailing_stop:
            atr_stop = self.highest_since_entry - self.atr[0] * self.p.stop_atr_multi
            hard_stop = self.entry_price * (1 - self.p.hard_stop_pct / 100)
            new_stop = max(atr_stop, hard_stop)
            if new_stop > self.stop_price:
                self.stop_price = new_stop

        # 加仓逻辑
        fast_rising = self.ma_fast[0] > self.ma_fast[-1]
        trend_strong = self.adx[0] > self.p.adx_threshold
        if (
            fast_rising
            and trend_strong
            and self.add_count < self.p.max_add_times
            and price > self.entry_price * 1.03
        ):
            cash = self.broker.getcash()
            add_size = (cash * self.p.add_pos_pct / 100) / price
            if add_size > 0:
                self.buy(size=add_size)
                self.add_count += 1

        # 离场判断（优先级从高到低）
        if price < self.stop_price:
            self.close()
        elif self.crossover[0] < 0:
            self.close()
        elif (self.data.datetime.date(0) - self.entry_date).days > 60:
            self.close()
