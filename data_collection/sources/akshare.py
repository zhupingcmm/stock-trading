"""AkShare 数据源适配。

封装 ``akshare`` 库的宏观经济与利率接口，屏蔽具体函数名与异常处理。
上层 ``collectors`` 仅面向本模块接口编程。
"""
from __future__ import annotations

import pandas as pd

try:
    import akshare as ak
except ImportError as exc:  # pragma: no cover - akshare 缺失时给出友好错误
    ak = None  # type: ignore[assignment]
    _IMPORT_ERROR: Exception | None = exc
else:
    _IMPORT_ERROR = None


class AkshareDataSource:
    """基于 akshare 的宏观数据源。

    所有 ``ak.x`` 调用集中在该类内，遇到异常时返回空 ``DataFrame``，
    由上层决定如何处理（参考脚本的语义是「失败跳过」）。
    """

    def __init__(self) -> None:
        if ak is None:  # pragma: no cover
            raise ImportError(
                "akshare 未安装，请先 ``pip install akshare``。"
                f"原始错误：{_IMPORT_ERROR}"
            )

    # ----- 月度指标 -----
    def get_cpi(self) -> pd.DataFrame:
        """CPI 同比。"""
        try:
            return ak.macro_china_cpi()
        except Exception:
            return pd.DataFrame()

    def get_ppi(self) -> pd.DataFrame:
        """PPI 同比。"""
        try:
            return ak.macro_china_ppi()
        except Exception:
            return pd.DataFrame()

    def get_pmi(self) -> pd.DataFrame:
        """制造业 PMI。"""
        try:
            return ak.macro_china_pmi()
        except Exception:
            return pd.DataFrame()

    def get_m2(self) -> pd.DataFrame:
        """货币供应 M2 同比增速。"""
        try:
            return ak.macro_china_supply_of_money()
        except Exception:
            return pd.DataFrame()

    def get_shrzgm(self) -> pd.DataFrame:
        """社会融资规模增量。"""
        try:
            return ak.macro_china_shrzgm()
        except Exception:
            return pd.DataFrame()

    def get_lpr(self) -> pd.DataFrame:
        """LPR 1Y / 5Y。"""
        try:
            return ak.macro_china_lpr()
        except Exception:
            return pd.DataFrame()

    # ----- 日频利率 -----
    def get_bond_yield(self, start_date: str) -> pd.DataFrame:
        """中美 10 年期国债收益率。

        ``start_date`` 为 ``YYYYMMDD`` 字符串。
        """
        try:
            return ak.bond_zh_us_rate(start_date=start_date)
        except Exception:
            return pd.DataFrame()

    # ----- 个股新闻 -----
    def get_stock_news(self, symbol: str) -> pd.DataFrame:
        """东方财富个股新闻。

        ``symbol`` 为纯数字代码（不带 ``.SH`` / ``.SZ`` 后缀）。
        """
        try:
            return ak.stock_news_em(symbol=symbol)
        except Exception:
            return pd.DataFrame()

    # ----- 研报数据 -----
    def get_institute_recommend(self, symbol: str) -> pd.DataFrame:
        """东方财富机构评级明细（每次券商发布的研究记录）。

        ``symbol`` 为纯数字代码（不带 ``.SH`` / ``.SZ`` 后缀）。
        """
        try:
            return ak.stock_institute_recommend_detail(symbol=symbol)
        except Exception:
            return pd.DataFrame()

    def get_profit_forecast_ths(self, symbol: str, indicator: str) -> pd.DataFrame:
        """同花顺盈利预测一致预期。

        ``indicator`` 取 ``"预测年报每股收益"`` 或 ``"预测年报净利润"``。
        """
        try:
            return ak.stock_profit_forecast_ths(symbol=symbol, indicator=indicator)
        except Exception:
            return pd.DataFrame()

    # ----- 财经日历 -----
    def get_economic_calendar(self, date_str: str) -> pd.DataFrame:
        """百度财经日历（按日查询）。

        ``date_str`` 格式 ``YYYYMMDD``。
        """
        try:
            return ak.news_economic_baidu(date=date_str)
        except Exception:
            return pd.DataFrame()