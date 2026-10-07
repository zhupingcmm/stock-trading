"""财经日历采集器。

把参考脚本 ``6-财经日历采集.py`` 的逻辑整合为 ``CalendarCollector``：
- 单次采集「今天-7 ~ 今天+30」窗口的财经日历
- 仅保留目标国家（中国/美国/欧元区/日本/英国）
- 事件按关键词分类写入 ``trade_calendar_event``
- ON DUPLICATE KEY UPDATE 使用 COALESCE 模式（仅新值非 NULL 时覆盖）
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import pandas as pd

from config.settings import (
    CALENDAR_COUNTRIES,
    CALENDAR_DAYS_BACK,
    CALENDAR_DAYS_FORWARD,
    CALENDAR_SOURCE_LABEL,
)
from data_collection.sources.akshare import AkshareDataSource
from data_collection.storage.mysql import MysqlStorage


# 事件类型分类关键词（与参考脚本保持一致）
EVENT_TYPE_MAP: dict[str, list[str]] = {
    "interest_rate": ["利率", "FOMC", "加息", "降息", "LPR", "基准利率", "联邦基金"],
    "inflation": ["CPI", "PPI", "通胀", "物价"],
    "employment": ["就业", "非农", "失业率", "ADP"],
    "pmi": ["PMI", "采购经理"],
    "gdp": ["GDP", "国内生产总值"],
    "trade": ["贸易", "进出口", "出口", "进口"],
    "monetary": ["M2", "货币供应", "社融", "信贷"],
    "housing": ["房价", "房屋"],
    "retail": ["零售", "消费"],
    "industry": ["工业", "产出", "产值"],
}


INSERT_SQL = """
    INSERT INTO trade_calendar_event
    (event_date, event_time, title, country, category,
     importance, forecast_value, actual_value, previous_value, source)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    actual_value   = COALESCE(VALUES(actual_value), actual_value),
    forecast_value = COALESCE(VALUES(forecast_value), forecast_value),
    previous_value = COALESCE(VALUES(previous_value), previous_value),
    importance     = VALUES(importance)
"""

# 动态列名匹配关键词（与参考脚本 col_map 一致）
_COL_KEYWORDS: dict[str, list[str]] = {
    "date": ["日期"],
    "time": ["时间"],
    "country": ["国家", "地区"],
    "event": ["事件"],
    "actual": ["实际"],
    "forecast": ["预期"],
    "previous": ["前值"],
    "importance": ["重要"],
}


@dataclass
class CalendarReport:
    """财经日历采集结果汇总。"""

    raw_count: int = 0
    filtered_count: int = 0
    saved: int = 0
    elapsed: float = 0.0


def classify_event(event_name: str) -> str:
    """根据事件名称分类（第一个匹配的关键词决定分类）。"""
    if not event_name:
        return "other"
    for etype, keywords in EVENT_TYPE_MAP.items():
        for kw in keywords:
            if kw in event_name:
                return etype
    return "other"


def _to_str(val) -> str | None:
    """将值转为字符串；``None`` / NaN / 空字符串 → ``None``。"""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val).strip()
    return s if s else None


def _find_col_by_keyword(columns: pd.Index, keywords: list[str]) -> str | None:
    """在列名中按关键词顺序查找第一个匹配列。"""
    for kw in keywords:
        for col in columns:
            if kw in str(col):
                return col
    return None


class CalendarCollector:
    """财经日历采集（百度财经口径）。"""

    COUNTRIES = CALENDAR_COUNTRIES
    SOURCE_LABEL = CALENDAR_SOURCE_LABEL

    def __init__(
        self,
        source: AkshareDataSource,
        storage: MysqlStorage,
        days_back: int | None = None,
        days_forward: int | None = None,
    ) -> None:
        self._source = source
        self._storage = storage
        self._days_back = days_back if days_back is not None else CALENDAR_DAYS_BACK
        self._days_forward = (
            days_forward if days_forward is not None else CALENDAR_DAYS_FORWARD
        )

    # ============================================================
    # 数据拉取与规整
    # ============================================================

    def fetch_range(self) -> pd.DataFrame:
        """按天循环调用百度财经日历接口，返回 ``pd.concat`` 后的全量 DataFrame。"""
        today = pd.Timestamp.now().normalize()
        dates = pd.date_range(
            today - pd.Timedelta(days=self._days_back),
            today + pd.Timedelta(days=self._days_forward),
        )
        frames: list[pd.DataFrame] = []
        for d in dates:
            date_str = d.strftime("%Y%m%d")
            df = self._source.get_economic_calendar(date_str)
            if df is not None and not df.empty:
                frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def _resolve_columns(self, df: pd.DataFrame) -> dict[str, str]:
        """动态把「日期/时间/国家/...」关键词映射到具体列名。"""
        col_map: dict[str, str] = {}
        for key, keywords in _COL_KEYWORDS.items():
            col_map[key] = _find_col_by_keyword(df.columns, keywords) or ""
        return col_map

    def _filter_country(self, df: pd.DataFrame, col_map: dict[str, str]) -> pd.DataFrame:
        """按国家白名单过滤。"""
        country_col = col_map.get("country")
        if not country_col or country_col not in df.columns:
            return df
        return df[df[country_col].isin(self.COUNTRIES)].reset_index(drop=True)

    def save(self, df: pd.DataFrame) -> int:
        """写入 ``trade_calendar_event``，返回处理的行数。

        空 DataFrame、国家过滤为空或关键列缺失时直接返回 0。
        """
        if df is None or df.empty:
            return 0

        col_map = self._resolve_columns(df)
        if not col_map.get("date") or not col_map.get("event"):
            print(
                f"  列名无法识别: date={col_map.get('date')!r} "
                f"event={col_map.get('event')!r}"
            )
            return 0

        df = self._filter_country(df, col_map)

        saved = 0
        for _, row in df.iterrows():
            event_date_raw = row[col_map["date"]]
            if pd.isna(event_date_raw):
                continue
            if hasattr(event_date_raw, "strftime"):
                event_date_str = event_date_raw.strftime("%Y-%m-%d")
            else:
                event_date_str = str(event_date_raw)[:10]

            title_raw = row[col_map["event"]]
            title = str(title_raw).strip()
            if not title:
                continue

            time_col = col_map.get("time")
            event_time = (
                str(row.get(time_col, "")).strip() if time_col and time_col in df.columns else ""
            )
            event_time = event_time or None

            country_col = col_map.get("country")
            country = (
                str(row.get(country_col, "")).strip()
                if country_col and country_col in df.columns
                else ""
            )

            importance_col = col_map.get("importance")
            importance = 1
            if importance_col and importance_col in df.columns:
                try:
                    importance = int(row.get(importance_col, 1) or 1)
                except (ValueError, TypeError):
                    importance = 1

            category = classify_event(title)

            actual_col = col_map.get("actual")
            forecast_col = col_map.get("forecast")
            previous_col = col_map.get("previous")

            actual = (
                _to_str(row.get(actual_col))
                if actual_col and actual_col in df.columns
                else None
            )
            forecast = (
                _to_str(row.get(forecast_col))
                if forecast_col and forecast_col in df.columns
                else None
            )
            previous = (
                _to_str(row.get(previous_col))
                if previous_col and previous_col in df.columns
                else None
            )

            self._storage.execute(INSERT_SQL, (
                event_date_str, event_time, title, country, category,
                importance, forecast, actual, previous, self.SOURCE_LABEL,
            ))
            saved += 1

        return saved

    # ============================================================
    # 主流程
    # ============================================================

    def collect(self) -> CalendarReport:
        """执行财经日历采集（today-back ~ today+forward 窗口）。"""
        report = CalendarReport()
        start_ts = time.time()

        print("=" * 60)
        print("财经日历采集 (百度财经口径)")
        print(
            f"窗口: today-{self._days_back} ~ today+{self._days_forward} "
            f"({self._days_back + self._days_forward + 1} 天)"
        )
        print("=" * 60)

        print("\n拉取数据...")
        df = self.fetch_range()
        report.raw_count = len(df)
        print(f"  原始数据: {report.raw_count} 条")

        if df.empty:
            print("  接口返回空，无可写入数据")
            report.elapsed = time.time() - start_ts
            self._print_summary(report)
            return report

        col_map = self._resolve_columns(df)
        country_col = col_map.get("country")
        if country_col and country_col in df.columns:
            filtered = df[df[country_col].isin(self.COUNTRIES)]
            report.filtered_count = len(filtered)
            print(
                f"  国家过滤 ({'/'.join(self.COUNTRIES)}): "
                f"{report.filtered_count} 条"
            )
        else:
            report.filtered_count = report.raw_count

        print("\n写入数据库...")
        report.saved = self.save(df)
        print(f"  写入/更新 {report.saved} 条事件")

        report.elapsed = time.time() - start_ts
        self._print_summary(report)
        return report

    # ============================================================
    # 摘要
    # ============================================================

    def _print_summary(self, report: CalendarReport | None = None) -> None:
        rows = self._storage.fetch_all(
            "SELECT country, COUNT(*) AS cnt, "
            "MIN(event_date) AS min_d, MAX(event_date) AS max_d "
            "FROM trade_calendar_event "
            "GROUP BY country ORDER BY cnt DESC"
        )
        if rows:
            print("\ntrade_calendar_event 概况:")
            for r in rows:
                print(
                    f"  {r['country']}: {r['cnt']} 条 "
                    f"({r['min_d']} ~ {r['max_d']})"
                )
        total = self._storage.fetch_all(
            "SELECT COUNT(*) AS c FROM trade_calendar_event"
        )
        if total:
            print(f"  总计: {total[0]['c']} 条")
        if report is not None:
            print("=" * 60)
            print(
                f"财经日历采集完成! 耗时 {report.elapsed:.1f} 秒 "
                f"(本次新增/更新 {report.saved} 条)"
            )
            print("=" * 60)