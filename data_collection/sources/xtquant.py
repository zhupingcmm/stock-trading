"""xtquant 数据源适配。

封装 MiniQMT 客户端 ``xtdata``，屏蔽 Windows/QMT 依赖细节，
上层 ``collectors`` 仅面向本模块接口编程。
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd

try:
    from xtquant import xtdata
except ImportError as exc:  # pragma: no cover - xtquant 仅 Windows + QMT 环境可用
    xtdata = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


class XtQuantDataSource:
    """基于 xtquant 的数据源。

    所有 ``xtdata`` 调用集中在该类内，方便在测试中以 mock 替换。
    """

    def __init__(self) -> None:
        if xtdata is None:  # pragma: no cover
            raise ImportError(
                "xtquant 未安装，请确认在 Windows + MiniQMT 环境下运行。"
                f"原始错误：{_IMPORT_ERROR}"
            )

    # ----- 连接 -----
    def connect(self) -> None:
        """连接 QMT 数据服务。"""
        xtdata.connect()

    # ----- 股票列表 -----
    def list_stocks(self, sector: str) -> list[str]:
        """获取指定板块下的股票列表，过滤掉不含 ``.`` 的代码。"""
        codes = xtdata.get_stock_list_in_sector(sector)
        return [str(c) for c in codes if "." in str(c)]

    # ----- 历史数据 -----
    def download_history(
        self,
        code: str,
        period: str = "1d",
        start_time: str | None = None,
    ) -> None:
        """触发 QMT 下载/刷新指定股票的历史数据。"""
        xtdata.download_history_data(code, period, start_time=start_time)

    def get_market_data(
        self,
        code: str,
        period: str = "1d",
        start_time: str | None = None,
        fields: Iterable[str] = ("open", "high", "low", "close", "volume", "amount"),
    ) -> pd.DataFrame | None:
        """获取行情数据，前复权。空数据返回 ``None``。"""
        data = xtdata.get_market_data_ex(
            field_list=list(fields),
            stock_list=[code],
            period=period,
            start_time=start_time,
            dividend_type="front",
        )
        if not data or code not in data:
            return None
        return data[code]

    # ----- 基础信息 -----
    def get_float_shares(self, code: str) -> int:
        """获取流通股本（股）。

        优先 ``NegotiableVolume``，缺失则回退 ``TotalVolume``，都缺失返回 0。
        """
        try:
            detail = xtdata.get_instrument_detail(code)
        except Exception:
            return 0
        if not detail:
            return 0
        neg = detail.get("NegotiableVolume") or detail.get("TotalVolume") or 0
        return int(neg) if neg > 0 else 0