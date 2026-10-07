"""项目配置入口。

通过 ``python-dotenv`` 加载项目根 ``.env`` 中的数据库/QMT 相关变量。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

# 项目根目录（``config/`` 的上一级）
ROOT = Path(__file__).resolve().parent.parent

# 从项目根 .env 读取，缺文件时返回空 dict 不抛错
_ENV = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}


# ---------- 数据采集 ----------
DATA_ROOT = "./data"

# 默认数据源标识（与 ``data_collection/sources`` 中的实现对应）
DEFAULT_DATA_SOURCE = "xtquant"

# xtquant 板块命名
SECTOR = "沪深A股"

# 首次全量采集的起始日期（YYYYMMDD）
DATA_START = "20230101"

# 并行下载线程数
NUM_WORKERS = 8

# 默认测试股票：600519.SH（贵州茅台）
TEST_MODE = True
TEST_STOCK = "600519.SH"

# ---------- 财务采集 ----------
FINANCIAL_DATA_START = "20150101"
FINANCIAL_BATCH_SIZE = 50
FINANCIAL_TABLE_LIST = ["Balance", "Income", "CashFlow", "PershareIndex", "Capital"]
# xtquant 财务下载等待超时（秒）
FINANCIAL_DOWNLOAD_TIMEOUT = 120

# ---------- 回测 ----------
# 初始资金（元）
BACKTEST_INITIAL_CASH = 1_000_000
# 单边手续费（万分之 2 = 0.0002）
BACKTEST_COMMISSION = 0.0002
# 默认仓位比例（95% 上限，留 5% 给费用/滑点缓冲）
BACKTEST_POSITION_PCT = 95
# 默认回测标的与时间窗口（CLI 参数可覆盖）
BACKTEST_STOCK_CODE = "603501.SH"
BACKTEST_START_DATE = "2024-01-01"
BACKTEST_END_DATE = "2026-10-07"

# ---------- 宏观采集 ----------
MACRO_RETENTION_YEARS = 10       # 月度指标保留窗口
MACRO_RATE_HISTORY_YEARS = 3     # 日频国债收益率回溯窗口
MACRO_DATA_SOURCE_LABEL = "akshare"

# ---------- 新闻采集 ----------
NEWS_NUM_WORKERS = 8
NEWS_CONTENT_MAX_LEN = 2000      # 单条 content 最大字符数
NEWS_DEFAULT_TYPE = "news"       # news_type 列默认值（announcement/news/report）
NEWS_DEFAULT_SOURCE = "eastmoney"

# ---------- 研报采集 ----------
REPORT_NUM_WORKERS = 4
REPORT_MAX_RECOMMEND_ROWS = 50
REPORT_RECENT_DAYS = 7
REPORT_SOURCE_EASTMONEY = "eastmoney"
REPORT_SOURCE_THS = "ths_consensus"

# ---------- 财经日历采集 ----------
CALENDAR_DAYS_BACK = 7
CALENDAR_DAYS_FORWARD = 30
CALENDAR_COUNTRIES = frozenset({"中国", "美国", "欧元区", "日本", "英国"})
CALENDAR_SOURCE_LABEL = "baidu_economic"

# ---------- 股票元数据采集 ----------
STOCK_META_NUM_WORKERS = 8
STOCK_META_DEFAULT_SECTOR = "沪深A股"
STOCK_META_SOURCE_LABEL = "qmt"

# ---------- 催化剂采集（Qwen Max 联网搜索） ----------
CATALYST_PROMPTS_PATH = ROOT / "config" / "prompts.yaml"
CATALYST_MODEL = "qwen-max"
CATALYST_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
CATALYST_SEARCH_DAYS = 180
CATALYST_MIN_IMPORTANCE = 2
CATALYST_MAX_IMPORTANCE = 3
CATALYST_PROMPT_BATCH_SIZE = 20
CATALYST_FUZZY_DEDUP_DAYS = 5
CATALYST_SOURCE_LABEL = "qwen_search"

# DashScope API Key（关键催化剂采集需要）
# 兼容参考脚本里的命名 DASHSCOPE_API_KEY
QWEN_API_KEY = _ENV.get("DASHSCOPE_API_KEY", "")

# ---------- 多因子选股 ----------
INDUSTRY_FACTOR_SCORE_MIN = 18
INDUSTRY_FACTOR_OUTPUT_ROOT = ROOT / "data" / "selection" / "industry_factor"
INDUSTRY_FACTOR_ENABLE_VIZ = True


@dataclass(frozen=True)
class MySQLConfig:
    """MySQL 连接配置。

    环境变量命名沿用参考项目 ``WUCAI_SQL_*``，便于直接复用既有 ``.env``。
    """

    host: str = _ENV.get("WUCAI_SQL_HOST", "localhost")
    user: str = _ENV.get("WUCAI_SQL_USERNAME", "root")
    password: str = _ENV.get("WUCAI_SQL_PASSWORD", "")
    database: str = _ENV.get("WUCAI_SQL_DB", "wucai_trade")
    port: int = int(_ENV.get("WUCAI_SQL_PORT", "3306"))
    charset: str = "utf8mb4"

    def as_pymysql_kwargs(self) -> dict:
        """转为 ``pymysql.connect`` 接受的参数。"""
        return {
            "host": self.host,
            "user": self.user,
            "password": self.password,
            "database": self.database,
            "port": self.port,
            "charset": self.charset,
        }


MYSQL_CONFIG = MySQLConfig()