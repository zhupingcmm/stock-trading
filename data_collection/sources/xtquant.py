"""xtquant 数据源适配。

封装 MiniQMT 客户端 ``xtdata``，屏蔽 Windows/QMT 依赖细节，
上层 ``collectors`` 仅面向本模块接口编程。
"""
from __future__ import annotations

from typing import Callable, Iterable

import pandas as pd  # noqa: F401  -- re-exported for downstream type hints

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

    def get_stock_name(self, code: str) -> str:
        """获取股票名称，单只。失败 / 不存在返回空字符串。"""
        try:
            detail = xtdata.get_instrument_detail(code)
        except Exception:
            return ""
        if not detail:
            return ""
        return str(detail.get("InstrumentName") or "").strip()

    def get_stock_names(self, codes: list[str]) -> dict[str, str]:
        """批量获取 ``{code: stock_name}``。失败 / 不存在的代码 → 空字符串。

        QMT 未启动或单只失败时不影响其他结果。
        """
        result: dict[str, str] = {}
        for code in codes:
            result[code] = self.get_stock_name(code)
        return result

    # ----- 财务数据 -----
    def download_financial_data(
        self,
        stocks: list[str],
        tables: list[str],
        start_time: str,
        end_time: str,
        callback: Callable[[dict], None] | None = None,
    ) -> None:
        """批量下载财务数据（异步，通过 callback 通知完成）。

        ``xtdata.download_financial_data2`` 接受一个 ``stock_list`` 参数，
        一次调用即可触发多只股票的下载。
        """
        xtdata.download_financial_data2(
            stock_list=stocks,
            table_list=tables,
            start_time=start_time,
            end_time=end_time,
            callback=callback,
        )

    def get_financial_data(
        self,
        stocks: list[str],
        tables: list[str],
        start_time: str,
        end_time: str,
        report_type: str = "report_time",
    ) -> dict | None:
        """获取财务数据，返回 ``{code: {table: [records]}}`` 或 ``None``。"""
        return xtdata.get_financial_data(
            stock_list=stocks,
            table_list=tables,
            start_time=start_time,
            end_time=end_time,
            report_type=report_type,
        )

    # ----- 行业映射 -----

    # 不同版本 QMT 对申万一级行业的板块命名约定：
    #   - SW1xxx   旧版 / 自定义
    #   - SWHY1xxx 新版 (HangYe)
    #   - THSSW1xxx / THS_SW1xxx  同花顺口径
    # 同时过滤掉带「加权」字样的衍生板块。
    _SW_INDUSTRY_PREFIXES: tuple[str, ...] = ("SW1", "SWHY1", "THSSW1", "THS_SW1")

    @classmethod
    def _is_sw_industry_sector(cls, name: object) -> bool:
        """判断板块名是否为申万一级行业（兼容多种前缀命名约定）。"""
        text = str(name)
        if "加权" in text:
            return False
        upper = text.upper()
        return any(upper.startswith(p) for p in cls._SW_INDUSTRY_PREFIXES)

    def get_stock_industry_map(self) -> dict[str, str]:
        """反向构建 ``{stock_code: industry}`` 映射，遍历申万一级行业板块。

        行业板块命名约定：``SW1`` / ``SWHY1`` / ``THSSW1`` / ``THS_SW1`` 前缀之一
        且不含「加权」字样。
        异常不再静默吞掉：网络/QMT 错误会打印堆栈，便于定位根因。
        """
        # 触发板块数据下载（如果 QMT 已加载则 no-op；缺失该 API 也不报错）
        download_fn = getattr(xtdata, "download_sector_data", None)
        if callable(download_fn):
            try:
                download_fn()
            except Exception as exc:
                print(
                    f"[warn] download_sector_data 失败: "
                    f"{type(exc).__name__}: {exc}"
                )

        try:
            all_sectors = xtdata.get_sector_list()
        except Exception as exc:
            print(
                f"[error] get_sector_list 失败: "
                f"{type(exc).__name__}: {exc}"
            )
            return {}

        sw_sectors = [s for s in all_sectors if self._is_sw_industry_sector(s)]
        if not sw_sectors:
            sample = [str(s) for s in all_sectors[:20]]
            print(
                "[warn] 未匹配到任何申万一级行业板块。"
                f"已检查 {len(all_sectors)} 个板块，前 20 个示例: {sample}"
            )
            return {}

        stock_to_industry: dict[str, str] = {}
        for sector in sw_sectors:
            try:
                stocks = xtdata.get_stock_list_in_sector(sector)
            except Exception as exc:
                print(
                    f"[warn] get_stock_list_in_sector({sector}) 失败: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if not stocks:
                continue
            for stk in stocks:
                code = str(stk)
                if "." in code and code not in stock_to_industry:
                    stock_to_industry[code] = sector

        return stock_to_industry