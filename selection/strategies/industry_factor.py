"""行业因子选股策略（多因子选股 - 筛选2）。

把参考脚本 ``多因子选股-筛选2.py`` 的整体流程编排为 ``IndustryFactorStrategy``：

1. ``FinancialFactorComputer.build_pool()``  拉财务数据 + 计算指标（同时回填 stock_name/industry）
2. ``IndustryScoreRanker.rank(pool)``  计算 pct + score
3. ``ScoreThresholdFilter(min_score).apply(...)``  阈值过滤
4. 落盘（CSV + 可视化）+ 打印达标股票 + 各行业分布表

数据源约束：选股阶段只读 MySQL，不再访问 xtquant。
``industry`` 缺失股票由 ``IndustryScoreRanker`` 自动降级为「全市场排名」。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from data_collection.storage.mysql import MysqlStorage
from config.settings import (
    INDUSTRY_FACTOR_ENABLE_VIZ,
    INDUSTRY_FACTOR_OUTPUT_ROOT,
    INDUSTRY_FACTOR_SCORE_MIN,
)
from selection.factors.financial import FinancialFactorComputer
from selection.filters.score_threshold import ScoreThresholdFilter
from selection.ranking.industry_score import IndustryScoreRanker


# ============================================================
# 报表
# ============================================================

@dataclass
class IndustryFactorReport:
    """策略运行结果汇总。"""

    pool_size: int = 0
    n_with_industry: int = 0
    used_industry: bool = False
    passed: int = 0
    min_score: int = 0
    output_csv: str = ""
    output_dir: str = ""
    elapsed: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


# ============================================================
# 策略
# ============================================================

class IndustryFactorStrategy:
    """行业因子选股编排。"""

    DEFAULT_METRICS_FOR_VIZ = ("roe", "grossprofit_margin", "debt_to_assets")
    METRICS_FOR_DIST_STATS = (
        "roe", "netprofit_yoy", "grossprofit_margin",
        "debt_to_assets", "ocf_to_revenue",
    )

    def __init__(
        self,
        storage: MysqlStorage,
        min_score: int | None = None,
        output_dir: Path | str | None = None,
        enable_viz: bool | None = None,
    ) -> None:
        self._storage = storage
        self._factor_computer = FinancialFactorComputer(storage)
        self._ranker = IndustryScoreRanker()
        self._min_score = min_score if min_score is not None else INDUSTRY_FACTOR_SCORE_MIN
        self._enable_viz = (
            enable_viz if enable_viz is not None else INDUSTRY_FACTOR_ENABLE_VIZ
        )
        self._output_root = (
            Path(output_dir) if output_dir else INDUSTRY_FACTOR_OUTPUT_ROOT
        )

    # ============================================================
    # 主流程
    # ============================================================

    def run(self) -> IndustryFactorReport:
        """执行一次完整选股流程。"""
        report = IndustryFactorReport(min_score=self._min_score)
        start_ts = time.time()

        run_dir = self._output_root / datetime.now().strftime("%Y%m%d")
        viz_dir = run_dir / "industry_viz"
        report.output_dir = str(run_dir)

        print("=" * 60)
        print("多因子选股 - 行业版 (industry_factor)")
        print(
            f"  打分制：5 项各 1~5 分，总分阈值 >= {self._min_score}（总分 5~25）"
        )
        print("=" * 60)

        # 1) 拉因子池（含 stock_name + industry，全部来自 MySQL）
        print("\n[1/4] 计算财务因子池...")
        pool = self._factor_computer.build_pool()
        report.pool_size = len(pool)
        summary = self._factor_computer.summarize(pool)
        if "industry" in pool.columns:
            n_with_industry = int(
                (pool["industry"].astype(str) != "").sum()
            )
        else:
            n_with_industry = 0
        report.n_with_industry = n_with_industry
        print(
            f"  共 {summary.n_stocks} 只股票"
            f"（含 roe: {summary.n_with_roe}，含 netprofit_yoy: {summary.n_with_yoy}，"
            f"含 industry: {n_with_industry}）"
        )

        if pool.empty:
            print("  因子池为空，无需选股")
            report.elapsed = time.time() - start_ts
            return report

        # 2) 行业排名 + 打分
        print("\n[2/4] 行业内排名打分...")
        rank_result = self._ranker.rank(pool)
        report.used_industry = rank_result.used_industry
        if rank_result.used_industry:
            print(f"  按 industry 分组排名（{rank_result.n_with_industry} 只）")
        else:
            print("  [warn] industry 全空，使用全市场排名")

        # 3) 阈值过滤
        print("\n[3/4] 阈值过滤...")
        flt = ScoreThresholdFilter(min_score=self._min_score)
        selected, filter_result = flt.apply(rank_result.df)
        report.passed = filter_result.passed
        print(
            f"  industry_score >= {self._min_score}: "
            f"{filter_result.passed}/{filter_result.total} 只"
        )

        # 4) 落盘 + 可视化
        print("\n[4/4] 落盘 + 可视化...")
        os.makedirs(run_dir, exist_ok=True)
        report.output_csv = self._save_output(run_dir, selected, rank_result.df)

        if self._enable_viz:
            self._save_visualization(rank_result.df, viz_dir)

        self._print_distribution_stats(rank_result.df)
        self._print_selected(selected)

        report.elapsed = time.time() - start_ts
        print("=" * 60)
        print(
            f"行业因子选股完成! 耗时 {report.elapsed:.1f} 秒, "
            f"达标 {report.passed} 只"
        )
        print("=" * 60)
        return report

    # ============================================================
    # 落盘
    # ============================================================

    def _save_output(
        self,
        run_dir: Path,
        selected: pd.DataFrame,
        full: pd.DataFrame,
    ) -> str:
        """把达标股票写入 ``output.csv``，返回路径。"""
        out_path = Path(run_dir) / "output.csv"
        if selected.empty:
            selected.to_csv(out_path, index=False, encoding="utf-8-sig")
            print(f"  0 只达标，已写空 CSV 到 {out_path}")
            return str(out_path)

        selected.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"  已写 {len(selected)} 行 -> {out_path}")
        return str(out_path)

    def _save_visualization(self, df: pd.DataFrame, viz_dir: Path) -> None:
        """按行业生成 3 张指标分布图（贴原脚本 ``save_industry_visualization``）。"""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: F401
            plt.rcParams["font.sans-serif"] = [
                "Microsoft YaHei", "SimHei", "SimSun", "KaiTi",
            ]
            plt.rcParams["axes.unicode_minus"] = False
        except ImportError:
            print("  [warn] matplotlib 不可用，跳过可视化")
            return

        if "industry" not in df.columns or df["industry"].isna().all():
            print("  [warn] 行业列为空，跳过可视化")
            return

        valid = df["industry"].notna() & (df["industry"].astype(str) != "")
        if not bool(valid.any()):
            print("  [warn] 行业有效数据为 0，跳过可视化")
            return

        os.makedirs(viz_dir, exist_ok=True)

        for col, label in [
            ("roe", "ROE (%)"),
            ("grossprofit_margin", "毛利率 (%)"),
            ("debt_to_assets", "资产负债率 (%)"),
        ]:
            if col not in df.columns:
                continue
            sub = df.loc[valid, ["industry", col]].dropna(subset=[col])
            if sub.empty:
                continue
            ind_agg = sub.groupby("industry")[col].agg(["mean", "median", "count"])
            ind_agg = ind_agg[ind_agg["count"] >= 3]
            ascending = (col == "debt_to_assets")
            ind_agg = ind_agg.sort_values("mean", ascending=ascending)
            if ind_agg.empty:
                continue

            import matplotlib.pyplot as plt  # 二次导入避免 top-level 用不到时警告
            fig, ax = plt.subplots(figsize=(12, max(6, len(ind_agg) * 0.3)))
            ax.barh(range(len(ind_agg)), ind_agg["mean"], label="均值", alpha=0.8)
            ax.set_yticks(range(len(ind_agg)))
            ax.set_yticklabels(ind_agg.index, fontsize=8)
            ax.set_xlabel(label)
            ax.set_title(f"各行业{label}分布（均值）")
            ax.legend()
            plt.tight_layout()
            out_path = viz_dir / f"industry_{col}.png"
            plt.savefig(out_path, dpi=100, bbox_inches="tight")
            plt.close()
            print(f"  已保存行业分布图: {out_path}")

    # ============================================================
    # 打印
    # ============================================================

    def _print_distribution_stats(self, df: pd.DataFrame) -> None:
        """打印各行业指标分布表（贴 ``industry_distribution_stats``）。"""
        if "industry" not in df.columns or df["industry"].isna().all():
            return
        valid = df["industry"].notna() & (df["industry"].astype(str) != "")
        if not bool(valid.any()):
            return
        sub = df.loc[valid]
        metrics = [m for m in self.METRICS_FOR_DIST_STATS if m in sub.columns]
        if not metrics:
            return
        agg_dict = {m: ["mean", "median", "count"] for m in metrics}
        stats = sub.groupby("industry").agg(agg_dict).round(2)
        print("\n" + "=" * 60)
        print("各行业指标分布（全市场）：")
        print("=" * 60)
        pd.set_option("display.max_columns", 20)
        pd.set_option("display.width", 200)
        print(stats.to_string())

    def _print_selected(self, selected: pd.DataFrame) -> None:
        """打印前 20 个达标股票。"""
        if selected.empty:
            return
        print("\n" + "=" * 60)
        print("达标股票（按总分排序）：")
        print("=" * 60)
        disp_cols = [
            "stock_code", "stock_name", "industry", "industry_score",
            "end_date", "roe", "netprofit_yoy", "grossprofit_margin",
            "debt_to_assets", "ocf_to_revenue",
        ]
        score_cols = [
            c for c in selected.columns
            if c.endswith("_industry_score") and c != "industry_score"
        ]
        cols = [c for c in disp_cols if c in selected.columns] + score_cols
        print(selected[cols].head(20).to_string(index=False))
