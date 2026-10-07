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