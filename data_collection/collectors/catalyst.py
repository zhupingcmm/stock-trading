"""关键催化剂事件采集器。

把参考脚本 ``7-关键催化剂采集.py`` 的逻辑整合为 ``CatalystCollector``：
- 通过 ``QwenClient``（DashScope 兼容模式 API）联网搜索未来 6 个月 A 股催化剂事件
- 为每个事件生成 AI 提问 prompt（分批 20 个/批）
- 写入 ``trade_calendar_event``（source='qwen_search'，importance ≥ 2）
- 提供 ``backfill_prompts()`` 给已有事件补 ``ai_prompt``
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import date as _date_cls, timedelta
from pathlib import Path
from typing import Any

import yaml

from config.settings import (
    CATALYST_FUZZY_DEDUP_DAYS,
    CATALYST_MAX_IMPORTANCE,
    CATALYST_MIN_IMPORTANCE,
    CATALYST_PROMPTS_PATH,
    CATALYST_PROMPT_BATCH_SIZE,
    CATALYST_SEARCH_DAYS,
    CATALYST_SOURCE_LABEL,
)
from data_collection.sources.llm import QwenClient
from data_collection.storage.mysql import MysqlStorage


# 写入主流程：importance 用 GREATEST(importance, VALUES) 保留较大值
INSERT_SQL = """
    INSERT INTO trade_calendar_event
    (event_date, event_time, title, country, category,
     importance, source, ai_prompt)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
    importance = GREATEST(importance, VALUES(importance)),
    category   = VALUES(category),
    source     = VALUES(source),
    ai_prompt  = COALESCE(VALUES(ai_prompt), ai_prompt)
"""

# 回填专用 SQL
UPDATE_PROMPT_SQL = (
    "UPDATE trade_calendar_event SET ai_prompt = %s WHERE id = %s"
)


@dataclass
class CatalystReport:
    """催化剂采集结果汇总。"""

    events_found: int = 0
    prompts_generated: int = 0
    saved: int = 0
    elapsed: float = 0.0


def _normalize_title(title: str) -> str:
    """标题归一化用于模糊去重：去除空格、斜杠、破折号、中英文括号。"""
    return re.sub(r"[\s/\-—()（）]", "", title or "")


def _parse_json_array(content: str) -> list[dict]:
    """从 LLM 输出中提取 JSON 数组（找最外层 [ ... ] 切片后 json.loads）。"""
    start = content.find("[")
    end = content.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        result = json.loads(content[start : end + 1])
    except (ValueError, TypeError):
        return []
    return result if isinstance(result, list) else []


class CatalystCollector:
    """关键催化剂事件采集（Qwen Max 联网搜索）。"""

    SOURCE_LABEL = CATALYST_SOURCE_LABEL

    def __init__(
        self,
        qwen: QwenClient,
        storage: MysqlStorage,
        prompts_path: Path | str | None = None,
        search_days: int | None = None,
        prompt_batch_size: int | None = None,
    ) -> None:
        self._qwen = qwen
        self._storage = storage
        self._prompts_path = Path(prompts_path) if prompts_path else CATALYST_PROMPTS_PATH
        self._search_days = search_days if search_days is not None else CATALYST_SEARCH_DAYS
        self._prompt_batch_size = (
            prompt_batch_size if prompt_batch_size is not None else CATALYST_PROMPT_BATCH_SIZE
        )

    # ============================================================
    # 配置与 Qwen 调用
    # ============================================================

    def load_prompts_config(self) -> dict[str, Any]:
        """读取 prompts.yaml（与参考脚本同名同语义）。"""
        with open(self._prompts_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def search_catalysts(self, cfg: dict[str, Any] | None = None) -> list[dict]:
        """联网搜索未来 N 天的关键催化剂事件。"""
        cfg = cfg or self.load_prompts_config()
        prompt_tpl = cfg["calendar"]["search_catalysts"]

        today = _date_cls.today()
        start_date = today.isoformat()
        end_date = (today + timedelta(days=self._search_days)).isoformat()

        prompt = prompt_tpl.format(start_date=start_date, end_date=end_date)
        print(f"  搜索范围: {start_date} ~ {end_date}")
        print("  调用 Qwen Max 联网搜索...")

        content = self._qwen.search(prompt, enable_search=True)
        print(f"  原始响应长度: {len(content)} 字符")

        events = _parse_json_array(content)
        if not events:
            print("  未找到 JSON 数组，原始内容前 500 字符：")
            print(content[:500])
            return []

        print(f"  解析到 {len(events)} 个事件")
        return events

    def generate_prompts(
        self,
        events: list[dict],
        cfg: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """为每个事件生成 AI 提问 prompt，返回 ``{title: ai_prompt}``。"""
        cfg = cfg or self.load_prompts_config()
        prompt_tpl = cfg["calendar"]["generate_prompts"]

        # 只传标题/日期/国家给 LLM，减少 token
        brief = [
            {"date": e.get("date", ""), "title": e.get("title", ""), "country": e.get("country", "")}
            for e in events
        ]

        all_prompts: dict[str, str] = {}
        total_batches = (len(brief) + self._prompt_batch_size - 1) // self._prompt_batch_size
        for i in range(0, len(brief), self._prompt_batch_size):
            batch = brief[i : i + self._prompt_batch_size]
            prompt = prompt_tpl.format(events_json=json.dumps(batch, ensure_ascii=False, indent=2))
            print(
                f"  生成prompt第 {i // self._prompt_batch_size + 1}/{total_batches} "
                f"批 ({len(batch)} 个事件)..."
            )
            content = self._qwen.search(prompt, enable_search=False)
            for r in _parse_json_array(content):
                title = (r.get("title") or "").strip()
                ai_prompt = (r.get("prompt") or "").strip()
                if title and ai_prompt:
                    all_prompts[title] = ai_prompt

        print(f"  共生成 {len(all_prompts)} 个prompt")
        return all_prompts

    # ============================================================
    # 主流程：save_events
    # ============================================================

    def _load_existing(self) -> dict[str, list[tuple[Any, _date_cls]]]:
        """一次性加载 ``qwen_search`` 已有事件，用于模糊去重。"""
        rows = self._storage.fetch_all(
            "SELECT id, event_date, title FROM trade_calendar_event "
            "WHERE source = %s",
            (self.SOURCE_LABEL,),
        )
        existing: dict[str, list[tuple[Any, _date_cls]]] = {}
        for r in rows:
            norm = _normalize_title(r["title"])
            existing.setdefault(norm, []).append((r["id"], r["event_date"]))
        return existing

    def save_events(
        self,
        events: list[dict],
        prompts_map: dict[str, str] | None = None,
    ) -> int:
        """把搜索到的事件写入数据库，先按 (归一化标题 + 日期 ±5 天) 去重。"""
        prompts_map = prompts_map or {}
        existing = self._load_existing()

        saved = 0
        for evt in events:
            date_str = (evt.get("date") or "").strip()
            title = (evt.get("title") or "").strip()
            if not date_str or not title:
                continue

            try:
                evt_date = _date_cls.fromisoformat(date_str)
            except ValueError:
                print(f"  跳过无效日期: {date_str} - {title}")
                continue

            # 模糊去重：归一化标题相同 + 日期差 ≤ 5 天视为重复
            norm = _normalize_title(title)
            skip = False
            for _ex_id, ex_date in existing.get(norm, []):
                if ex_date is None:
                    continue
                diff = abs((evt_date - ex_date).days)
                if 0 < diff <= CATALYST_FUZZY_DEDUP_DAYS:
                    skip = True
                    break
            if skip:
                continue

            country = (evt.get("country") or "中国").strip() or "中国"
            category = (evt.get("category") or "policy").strip() or "policy"
            raw_imp = evt.get("importance", CATALYST_MIN_IMPORTANCE)
            try:
                raw_imp = int(raw_imp)
            except (ValueError, TypeError):
                raw_imp = CATALYST_MIN_IMPORTANCE
            importance = max(
                CATALYST_MIN_IMPORTANCE,
                min(CATALYST_MAX_IMPORTANCE, raw_imp),
            )

            ai_prompt = prompts_map.get(title)

            self._storage.execute(INSERT_SQL, (
                date_str, None, title, country, category,
                importance, self.SOURCE_LABEL, ai_prompt,
            ))
            saved += 1

            # 写完同步进内存集合，避免同批内重复
            existing.setdefault(norm, []).append((None, evt_date))

        return saved

    # ============================================================
    # 回填：backfill_prompts
    # ============================================================

    def backfill_prompts(self) -> int:
        """为 ``source=qwen_search AND ai_prompt IS NULL`` 的事件补全 prompt。"""
        rows = self._storage.fetch_all(
            "SELECT id, event_date, title, country FROM trade_calendar_event "
            "WHERE source = %s "
            "AND (ai_prompt IS NULL OR ai_prompt = '') "
            "AND event_date >= CURDATE()",
            (self.SOURCE_LABEL,),
        )
        if not rows:
            print("所有事件已有prompt，无需补充")
            return 0

        print(f"需要补充prompt的事件: {len(rows)} 个")

        norm_id_map: dict[str, Any] = {}
        events: list[dict] = []
        for r in rows:
            norm_id_map[_normalize_title(r["title"])] = r["id"]
            events.append({
                "date": str(r["event_date"]),
                "title": r["title"],
                "country": r["country"],
            })

        prompts_map = self.generate_prompts(events)

        updated = 0
        for title, prompt_text in prompts_map.items():
            eid = norm_id_map.get(_normalize_title(title))
            if eid:
                self._storage.execute(UPDATE_PROMPT_SQL, (prompt_text, eid))
                updated += 1

        print(f"已补充 {updated} 个事件的prompt")
        return updated

    # ============================================================
    # 调度入口
    # ============================================================

    def run(self) -> CatalystReport:
        """执行主流程：搜索事件 → 生成 prompt → 写入数据库。"""
        report = CatalystReport()
        start_ts = time.time()

        print("=" * 60)
        print("关键催化剂事件采集 (Qwen Max 联网搜索)")
        print("=" * 60)

        try:
            cfg = self.load_prompts_config()
        except FileNotFoundError as exc:
            print(f"  prompts.yaml 加载失败: {exc}")
            report.elapsed = time.time() - start_ts
            return report

        events = self.search_catalysts(cfg)
        report.events_found = len(events)
        if not events:
            print("\n未获取到事件")
            report.elapsed = time.time() - start_ts
            return report

        # 打印预览
        print(f"\n事件预览 ({len(events)} 个):")
        for evt in events:
            imp = evt.get("importance", CATALYST_MIN_IMPORTANCE)
            stars = "*" * max(CATALYST_MIN_IMPORTANCE, min(CATALYST_MAX_IMPORTANCE, int(imp) if isinstance(imp, (int, float)) else CATALYST_MIN_IMPORTANCE))
            print(
                f"  [{stars}] {evt.get('date', '?')} "
                f"{evt.get('country', '?')} {evt.get('title', '?')}"
            )

        print("\n生成事件提问prompt...")
        prompts_map = self.generate_prompts(events, cfg)
        report.prompts_generated = len(prompts_map)

        report.saved = self.save_events(events, prompts_map)
        print(f"\n写入/更新 {report.saved} 条催化剂事件")

        report.elapsed = time.time() - start_ts
        self._print_summary()
        return report

    def run_backfill(self) -> int:
        """单独调度回填。"""
        print("=" * 60)
        print("催化剂事件 - 回填 ai_prompt")
        print("=" * 60)
        start_ts = time.time()
        try:
            cfg = self.load_prompts_config()
        except FileNotFoundError as exc:
            print(f"  prompts.yaml 加载失败: {exc}")
            return 0

        updated = self.backfill_prompts()
        elapsed = time.time() - start_ts
        print(f"\n回填完成! 共 {updated} 条, 耗时 {elapsed:.1f} 秒")
        return updated

    # ============================================================
    # 摘要
    # ============================================================

    def _print_summary(self) -> None:
        rows = self._storage.fetch_all(
            "SELECT importance, COUNT(*) AS cnt "
            "FROM trade_calendar_event WHERE source = %s "
            "GROUP BY importance ORDER BY importance DESC",
            (self.SOURCE_LABEL,),
        )
        if rows:
            print("\nqwen_search 来源统计:")
            for r in rows:
                print(f"  {r['importance']}星: {r['cnt']} 条")
        print("\n" + "=" * 60)
        print("催化剂采集完成!")
        print("=" * 60)