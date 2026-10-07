"""汇总表打印测试。

锁定边框表格 + 每列数字格式，避免回归。
"""
from __future__ import annotations

import io
import sys

import pytest

from backtest.reports.printer import (
    SUMMARY_COLS,
    _extract_row,
    _fmt_cell,
    print_summary_table,
)


# ---------- 单元：单元格格式化 ----------

def test_fmt_cell_label():
    assert _fmt_cell("经典海龟", "label") == "经典海龟"


def test_fmt_cell_pct_signed_keeps_sign():
    """pct_signed 必须带正负号，宽度 8。"""
    assert _fmt_cell(12.34, "pct_signed") == "  +12.34"
    assert _fmt_cell(-3.2, "pct_signed") == "   -3.20"


def test_fmt_cell_pct_no_sign():
    """pct 无正负号（回撤 / 胜率）。"""
    assert _fmt_cell(8.2, "pct") == "    8.20"
    assert _fmt_cell(-8.2, "pct") == "   -8.20"  # 回撤允许负号


def test_fmt_cell_num2():
    assert _fmt_cell(1.45, "num2") == "    1.45"


def test_fmt_cell_int():
    assert _fmt_cell(42.7, "int") == "42"


def test_fmt_cell_none_returns_na():
    assert _fmt_cell(None, "pct") == "N/A"
    assert _fmt_cell(None, "label") == "N/A"


# ---------- 单元：行抽取 ----------

def test_extract_row_multiplies_pct_keys_by_100():
    m = {"total_return": 0.1234, "annual_return": 0.08, "max_drawdown": -0.08,
         "sharpe_ratio": 1.45, "win_rate": 0.62, "benchmark_return": 0.045}
    row = _extract_row(m)
    assert row["total_return"] == pytest.approx(12.34)
    assert row["win_rate"] == pytest.approx(62.0)
    assert row["sharpe_ratio"] == 1.45  # 非百分比键原样


def test_extract_row_handles_missing_key():
    row = _extract_row({"label": "X", "total_return": None})
    assert row["total_return"] is None
    assert row["label"] == "X"


# ---------- 集成：边框表输出 ----------

def _capture(rows) -> str:
    """捕获 ``print_summary_table`` 的 stdout。"""
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        print_summary_table(rows, "600519.SH", "2025-01-01", "2025-12-31")
    finally:
        sys.stdout = old
    return buf.getvalue()


def test_print_summary_table_emits_grid_borders(capsys):
    """边框表必须包含 +---+---+ 分隔符。"""
    rows = [
        {"label": "经典海龟", "total_return": 12.34, "annual_return": 8.5,
         "max_drawdown": -8.2, "sharpe_ratio": 1.45, "calmar_ratio": 1.04,
         "win_rate": 62.0, "profit_loss_ratio": 2.31, "profit_factor": 1.78,
         "total_trades": 42, "benchmark_return": 4.5},
        {"label": "MACD", "total_return": -3.2, "annual_return": -2.2,
         "max_drawdown": -15.5, "sharpe_ratio": -0.18, "calmar_ratio": -0.14,
         "win_rate": 42.0, "profit_loss_ratio": 0.95, "profit_factor": 0.81,
         "total_trades": 52, "benchmark_return": 4.5},
    ]
    print_summary_table(rows, "600519.SH", "2025-01-01", "2025-12-31")
    out = capsys.readouterr().out
    # 至少 3 行 +---+---+（header + 中间 + 结尾）
    assert out.count("+---") >= 3
    assert out.count("|") >= 8  # 行首尾 + 单元格分隔
    assert "经典海龟" in out
    assert "MACD" in out


def test_print_summary_table_picks_best_and_worst():
    """最佳/最差高亮逻辑保留。"""
    rows = [
        {"label": "A", "total_return": 10.0, "annual_return": 5.0,
         "max_drawdown": -5.0, "sharpe_ratio": 1.0, "calmar_ratio": 1.0,
         "win_rate": 50.0, "profit_loss_ratio": 1.5, "profit_factor": 1.2,
         "total_trades": 20, "benchmark_return": 2.0},
        {"label": "B", "total_return": -5.0, "annual_return": -3.0,
         "max_drawdown": -20.0, "sharpe_ratio": -0.5, "calmar_ratio": -0.2,
         "win_rate": 30.0, "profit_loss_ratio": 0.8, "profit_factor": 0.6,
         "total_trades": 30, "benchmark_return": 2.0},
    ]
    out = _capture(rows)
    assert "最佳总收益:" in out
    assert "A" in out
    assert "最大回撤最小:" in out


def test_print_summary_table_empty():
    """空行时不抛错，打印提示。"""
    out = _capture([])
    assert "没有可用结果" in out


def test_summary_cols_is_three_tuple():
    """``SUMMARY_COLS`` 现在是三元组（key, 显示名, fmt）。"""
    for entry in SUMMARY_COLS:
        assert len(entry) == 3
