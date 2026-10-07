"""多周期融合海龟策略 — 周线定方向，日线找入场。

来源：CASE-海龟交易法则/3-多周期海龟策略.py

核心思想
--------
「大周期过滤，小周期执行」：
  - 周线级别判断大趋势方向
  - 日线级别执行海龟突破信号
  - 只在大趋势向下时禁止做多，其他情况（up / neutral）正常交易

周线过滤规则
------------
  - 周线收盘 > 周线通道上轨 → 大趋势向上（允许做多）
  - 周线收盘 < 周线通道下轨 → 大趋势向下（禁止做多，已持仓则平仓）
  - 其他情况（中性） → 允许做多（不能太严格，否则错过太多机会）

数据约定
--------
策略访问两个数据源：
  - ``self.data0``：日线 K 线（入场信号）
  - ``self.data1``：周线 K 线（趋势过滤）

必须使用 ``backtest.engine.setup_multi_tf_cerebro`` 配置 cerebro
（不是 ``setup_cerebro``），否则周线 data1 不存在。
"""
from __future__ import annotations

import numpy as np
import backtrader as bt


STRATEGY_META = {
    "name": "多周期海龟策略",
    "category": "trend",
    "desc": "周线 8 周通道定方向 + 日线 20 日通道找入场",
    "setup": "multi_tf",
    "params": {
        "daily_entry": 20,
        "daily_exit": 10,
        "weekly_period": 8,
        "atr_period": 20,
        "risk_pct": 1.0,
        "max_units": 4,
        "add_n": 0.5,
        "stop_n": 2.0,
    },
    "logic": "日线20日突破入场；周线8周通道向下 → 禁开新仓，已持仓平仓；"
             "ATR 仓位 + 金字塔加仓 + 2N 止损",
}


class Strategy(bt.Strategy):
    """多周期海龟策略：周线过滤 + 日线入场。"""

    params = (
        ("daily_entry", 20),
        ("daily_exit", 10),
        ("weekly_period", 8),
        ("atr_period", 20),
        ("risk_pct", 1.0),
        ("max_units", 4),
        ("add_n", 0.5),
        ("stop_n", 2.0),
    )

    def __init__(self):
        # 日线指标（data0）：入场/出场通道 + ATR
        self.daily_entry_high = bt.ind.Highest(
            self.data0.high, period=self.p.daily_entry,
        )
        self.daily_exit_low = bt.ind.Lowest(
            self.data0.low, period=self.p.daily_exit,
        )
        self.daily_atr = bt.ind.ATR(self.data0, period=self.p.atr_period)

        # 周线指标（data1）：趋势通道
        self.weekly_high = bt.ind.Highest(
            self.data1.high, period=self.p.weekly_period,
        )
        self.weekly_low = bt.ind.Lowest(
            self.data1.low, period=self.p.weekly_period,
        )

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
                self.stop_price = fp - self.p.stop_n * self.daily_atr[0]
                self.last_add_price = fp
            elif order.issell():
                self.units = 0
                self.entry_prices = []
                self.stop_price = 0.0
                self.last_add_price = 0.0
        self.order = None

    def _calc_unit_size(self) -> int:
        pv = self.broker.getvalue()
        atr_val = self.daily_atr[0]
        if atr_val <= 0:
            return 0
        risk_ratio = self.p.risk_pct / 100.0
        unit_size = (pv * risk_ratio) / atr_val
        unit_size = int(unit_size // 100) * 100
        return max(unit_size, 100)

    def _get_weekly_trend(self) -> str:
        """判断周线大趋势：``up`` / ``down`` / ``neutral``。

        周线收盘 > 周线 N 周高 → up
        周线收盘 < 周线 N 周低 → down
        其他 → neutral
        """
        try:
            weekly_close = self.data1.close[0]
            wh = self.weekly_high[-1]
            wl = self.weekly_low[-1]
        except (IndexError, AttributeError):
            return "neutral"
        if np.isnan(wh) or np.isnan(wl):
            return "neutral"
        if weekly_close > wh:
            return "up"
        if weekly_close < wl:
            return "down"
        return "neutral"

    def next(self):
        if self.order:
            return
        atr_val = self.daily_atr[0]
        if np.isnan(atr_val) or atr_val <= 0:
            return
        close = self.data0.close[0]
        weekly_trend = self._get_weekly_trend()

        if not self.position:
            # 周线趋势向下时不开仓；up / neutral 都允许（宽松过滤）
            if weekly_trend == "down":
                return
            if close > self.daily_entry_high[-1]:
                size = self._calc_unit_size()
                if size > 0:
                    self.order = self.buy(size=size)
        else:
            # 2N 硬止损优先
            if close < self.stop_price:
                self.order = self.close()
                return
            # 日线唐奇安通道出场
            if close < self.daily_exit_low[-1]:
                self.order = self.close()
                return
            # 周线转为下跌 → 趋势逆转保护（平仓）
            if weekly_trend == "down":
                self.order = self.close()
                return
            # 金字塔加仓
            if self.units < self.p.max_units:
                if close >= self.last_add_price + self.p.add_n * atr_val:
                    size = self._calc_unit_size()
                    cash = self.broker.getcash()
                    if size > 0 and cash > close * size * 1.01:
                        self.order = self.buy(size=size)
