"""``XtQuantDataSource`` 单元测试。

``xtquant`` 在非 Windows / 非 QMT 环境不可用，因此只测试纯 Python 的
工具方法 ``_is_sw_industry_sector``（不实例化 ``XtQuantDataSource``，
避免 ``xtdata`` 导入失败）。
"""
from __future__ import annotations

import pytest

from data_collection.sources.xtquant import XtQuantDataSource


# ---------- _is_sw_industry_sector ----------

class TestIsSwIndustrySector:
    """覆盖多版本 QMT 对申万一级行业的命名约定。"""

    @pytest.mark.parametrize("name", [
        "SW1银行",
        "SW1食品饮料",
        "SW1房地产",
        "sw1医药生物",   # 大小写不敏感
        "SWHY1银行",     # 新版 (HangYe)
        "swhy1食品饮料",
        "THSSW1银行",    # 同花顺口径
        "THS_SW1医药",
        "ths_sw1电子",
    ])
    def test_matches_sw_industry_names(self, name: str) -> None:
        assert XtQuantDataSource._is_sw_industry_sector(name) is True

    @pytest.mark.parametrize("name", [
        "SW1银行加权",         # 加权指数应排除
        "SWHY1食品饮料加权指数",
        "SW2银行",             # 二级行业（SW2/SWHY2）应排除
        "SWHY2房地产",
        "BK0001",              # 同花顺概念板块
        "THS_BK0001",
        "沪深300",
        "上证50",
        "",
        "行业",
    ])
    def test_rejects_non_sw1_names(self, name: str) -> None:
        assert XtQuantDataSource._is_sw_industry_sector(name) is False

    def test_accepts_non_string_objects(self) -> None:
        """``get_sector_list`` 可能返回非 str，统一 ``str()`` 后判断。"""
        assert XtQuantDataSource._is_sw_industry_sector(12345) is False
        assert XtQuantDataSource._is_sw_industry_sector(None) is False

    def test_prefixes_constant_covers_known_variants(self) -> None:
        """防止回归：前缀常量必须包含至少 ``SW1`` / ``SWHY1``。"""
        prefixes = XtQuantDataSource._SW_INDUSTRY_PREFIXES
        assert "SW1" in prefixes
        assert "SWHY1" in prefixes
