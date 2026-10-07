"""财务因子计算器。

把参考脚本 ``多因子选股-下载数据.py`` 中的指标抽取与 ``多因子选股-筛选2.py`` 的
打分输入数据需求，整合为一个 ``FinancialFactorComputer``。

输出列：
  - stock_code, stock_name, industry, end_date
  - roe, netprofit_yoy, grossprofit_margin, debt_to_assets, ocf_to_revenue

数据来源：MySQL 全部表：
  - ``trade_stock_financial``  拉最新一期财务记录 + 年报历史；
  - ``trade_stock_meta``  拉 ``{stock_code: stock_name, industry}``。
``industry`` 缺失则留空字符串，由 ``IndustryScoreRanker`` 走「全市场排名」降级路径。

性能：年报历史在 ``build_pool()`` 入口**一次性**拉全量，转 dict 缓存，
避免 N+1 查询（每只股票一次 fetch_all → 5000 只股票 = 5000 次往返）。
"""
from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

from data_collection.storage.mysql import MysqlStorage


# 拉每只股票最新一期的 SQL（只读 ``trade_stock_financial``）
_LATEST_RECORDS_SQL = """
    SELECT t.stock_code,
           t.report_date AS end_date,
           t.roe,
           t.gross_margin  AS grossprofit_margin,
           t.debt_ratio    AS debt_to_assets,
           t.operating_cashflow,
           t.revenue,
           t.net_profit
    FROM trade_stock_financial t
    INNER JOIN (
        SELECT stock_code, MAX(report_date) AS max_date
        FROM trade_stock_financial
        GROUP BY stock_code
    ) m ON m.stock_code = t.stock_code AND m.max_date = t.report_date
"""


# 拉年报历史的 SQL：仅取 12-31 结尾的报告期
_ANNUAL_HISTORY_SQL = """
    SELECT stock_code, report_date, net_profit
    FROM trade_stock_financial
    WHERE report_date LIKE %s
      AND net_profit IS NOT NULL
    ORDER BY stock_code, report_date DESC
"""


# 拉股票元数据：名称 + 行业，由 ``StockMetaCollector`` 写入
_META_SQL = """
    SELECT stock_code, stock_name, industry
    FROM trade_stock_meta
"""


@dataclass
class FactorPoolSummary:
    """财务因子池摘要。"""

    n_stocks: int = 0
    n_with_roe: int = 0
    n_with_yoy: int = 0


class FinancialFactorComputer:
    """从 MySQL 拉财务数据并计算 5 项选股指标。"""

    def __init__(self, storage: MysqlStorage, verbose: bool = True) -> None:
        self._storage = storage
        self._verbose = verbose

    # ============================================================
    # 主流程
    # ============================================================

    def build_pool(self) -> pd.DataFrame:
        """拉取每只股票最新一期的财务记录，并合并 ``trade_stock_meta`` 的名称 + 行业。

        返回 DataFrame，列为：
        ``stock_code, stock_name, industry, end_date, roe, netprofit_yoy,
        grossprofit_margin, debt_to_assets, ocf_to_revenue``。
        """
        t0 = time.time()
        self._log("  [1/5] 拉取每只股票最新一期财务记录...")
        df = self._fetch_latest()
        if df.empty:
            self._log(f"  [skip] trade_stock_financial 无记录，耗时 {time.time() - t0:.1f}s")
            return pd.DataFrame(columns=[
                "stock_code", "stock_name", "industry", "end_date",
                "roe", "netprofit_yoy", "grossprofit_margin",
                "debt_to_assets", "ocf_to_revenue",
            ])
        self._log(f"    -> {len(df)} 只股票最新一期 ({time.time() - t0:.1f}s)")

        # 数值化处理（DB 返回值通常已是 float，但 JSON 化或文本路径可能给 str）
        self._log("  [2/5] 数值化字段...")
        for col in ("roe", "grossprofit_margin", "debt_to_assets",
                    "operating_cashflow", "revenue", "net_profit"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 计算 ocf_to_revenue
        self._log("  [3/5] 计算 ocf_to_revenue...")
        df["ocf_to_revenue"] = df.apply(self._safe_ocf_to_revenue, axis=1)

        # 计算 netprofit_yoy：先一次性拉全量年报历史，建内存索引（避免 N+1）
        self._log("  [4/5] 拉取年报历史，计算 netprofit_yoy...")
        annual_history = self._fetch_annual_history()
        self._log(f"    -> {sum(len(v) for v in annual_history.values())} 条年报记录，"
                  f"{len(annual_history)} 只股票")
        df["netprofit_yoy"] = df["stock_code"].apply(
            lambda code: self._yoy_from_cache(code, annual_history),
        )

        # 从 trade_stock_meta 回填 stock_name + industry
        self._log("  [5/5] 回填 stock_name + industry (trade_stock_meta)...")
        meta = self._fetch_meta()
        if not meta.empty:
            df["stock_name"] = df["stock_code"].map(
                meta.set_index("stock_code")["stock_name"],
            ).fillna("")
            df["industry"] = df["stock_code"].map(
                meta.set_index("stock_code")["industry"],
            ).fillna("")
        else:
            df["stock_name"] = ""
            df["industry"] = ""
        self._log(f"    -> meta 覆盖 {len(meta)} 只")

        self._log(f"  build_pool 总耗时 {time.time() - t0:.1f}s")
        return df[[
            "stock_code", "stock_name", "industry", "end_date",
            "roe", "netprofit_yoy", "grossprofit_margin",
            "debt_to_assets", "ocf_to_revenue",
        ]]

    def summarize(self, df: pd.DataFrame) -> FactorPoolSummary:
        """统计因子池覆盖情况。"""
        if df.empty:
            return FactorPoolSummary()
        return FactorPoolSummary(
            n_stocks=len(df),
            n_with_roe=int(df["roe"].notna().sum()) if "roe" in df.columns else 0,
            n_with_yoy=int(df["netprofit_yoy"].notna().sum())
            if "netprofit_yoy" in df.columns else 0,
        )

    # ============================================================
    # 拉数
    # ============================================================

    def _fetch_latest(self) -> pd.DataFrame:
        """通过 ``fetch_all`` 拿每只股票最新一期的财务记录。"""
        rows = self._storage.fetch_all(_LATEST_RECORDS_SQL)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def _fetch_annual_history(self) -> dict[str, list[dict]]:
        """一次性拉取所有 12-31 年报历史，按 ``stock_code`` 索引并按日期降序。

        返回 ``{code: [{report_date, net_profit}, ...]}``，
        调用方在内存里按股票代码查即可，无需再访问 DB。
        """
        rows = self._storage.fetch_all(_ANNUAL_HISTORY_SQL, ("%-12-31",))
        history: dict[str, list[dict]] = defaultdict(list)
        if not rows:
            return history
        for r in rows:
            history[r["stock_code"]].append(r)
        # 降序排序（SQL 已经 ORDER BY 了一次，再排一次保证）
        for code in history:
            history[code].sort(key=lambda r: r["report_date"], reverse=True)
        return history

    def _fetch_meta(self) -> pd.DataFrame:
        """通过 ``fetch_all`` 拿 ``trade_stock_meta`` 全量 ``{code, name, industry}``。"""
        rows = self._storage.fetch_all(_META_SQL)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    # ============================================================
    # 单只指标
    # ============================================================

    @staticmethod
    def _safe_ocf_to_revenue(row: pd.Series) -> float | None:
        """``ocf_to_revenue = operating_cashflow / revenue * 100``，缺失/除零 → None。"""
        ocf = row.get("operating_cashflow")
        rev = row.get("revenue")
        if ocf is None or rev is None:
            return None
        try:
            ocf_v, rev_v = float(ocf), float(rev)
        except (ValueError, TypeError):
            return None
        if rev_v == 0 or math.isnan(rev_v) or math.isnan(ocf_v):
            return None
        result = round(ocf_v / rev_v * 100, 4)
        return result if result == result else None  # NaN guard

    @staticmethod
    def _yoy_from_cache(
        stock_code: str,
        history: dict[str, list[dict]],
    ) -> float | None:
        """从内存年报缓存里算 ``netprofit_yoy``，不再访问 DB。

        不足 2 期或上一期净利润为 0/缺失时返回 None。
        """
        annual = history.get(stock_code)
        if not annual or len(annual) < 2:
            return None
        latest = annual[0]
        prev = annual[1]
        try:
            cur_np = float(latest["net_profit"])
            prev_np = float(prev["net_profit"])
        except (ValueError, TypeError):
            return None
        if prev_np == 0 or math.isnan(prev_np) or math.isnan(cur_np):
            return None
        yoy = (cur_np - prev_np) / prev_np * 100
        return round(yoy, 2)

    # ============================================================
    # 日志
    # ============================================================

    def _log(self, msg: str) -> None:
        if self._verbose:
            print(msg)
