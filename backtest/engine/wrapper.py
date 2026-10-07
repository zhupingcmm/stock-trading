"""策略包装器：自动记录交易与每日净值。

用法::

    Wrapped = wrap_strategy(MyStrategy)
    cerebro.addstrategy(Wrapped, **params)

不修改原策略逻辑，仅追加 ``_trade_log`` / ``_nav_log`` 属性供报告层读取。
"""
from __future__ import annotations

from typing import Type


def wrap_strategy(strategy_class: Type) -> Type:
    """返回一个子类，自动在 ``notify_order`` / ``next`` 里记录交易与净值。"""

    class WrappedStrategy(strategy_class):  # type: ignore[misc, valid-type]
        def __init__(self):
            super().__init__()
            self._trade_log: list[dict] = []
            self._nav_log: list[dict] = []

        def notify_order(self, order):
            if order.status == order.Completed:
                self._trade_log.append({
                    "date": self.data.datetime.date(0),
                    "type": "BUY" if order.isbuy() else "SELL",
                    "price": round(order.executed.price, 2),
                    "size": abs(int(order.executed.size)),
                })
            super_notify = getattr(super(), "notify_order", None)
            if super_notify is not None:
                super_notify(order)

        def next(self):
            self._nav_log.append({
                "date": self.data.datetime.date(0),
                "nav": self.broker.getvalue(),
            })
            super().next()

    WrappedStrategy.__name__ = strategy_class.__name__
    WrappedStrategy.__qualname__ = strategy_class.__qualname__
    WrappedStrategy.__module__ = strategy_class.__module__
    return WrappedStrategy
