"""MySQL 存储后端。

与参考脚本 ``db_config.py`` 同样的 ``WUCAI_SQL_*`` 环境变量命名，
便于直接复用项目根 ``.env``。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from config.settings import MYSQL_CONFIG, MySQLConfig


class MysqlStorage:
    """基于 ``pymysql`` 的简单封装。

    每个方法独立短连接（与参考脚本风格一致），适合批量写入场景；
    若后续有高频调用需求，可改造为连接池。
    """

    def __init__(self, config: MySQLConfig | None = None) -> None:
        self._config = config or MYSQL_CONFIG

    # ----- 工厂 -----
    @classmethod
    def from_env(cls) -> "MysqlStorage":
        """从环境变量构建（默认使用 ``config.settings.MYSQL_CONFIG``）。"""
        return cls(MYSQL_CONFIG)

    # ----- 连接辅助 -----
    def _connect(self) -> pymysql.connections.Connection:
        return pymysql.connect(**self._config.as_pymysql_kwargs())

    @contextmanager
    def _cursor(self, dict_cursor: bool = False) -> Iterator:
        conn = self._connect()
        try:
            cursor = conn.cursor(DictCursor if dict_cursor else None)
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

    # ----- 写 -----
    def execute(self, sql: str, params: tuple | None = None) -> int:
        """单条 UPDATE/INSERT，返回受影响行数。"""
        with self._cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.rowcount

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        """批量 UPSERT，返回受影响行数。空列表直接返回 0。"""
        if not rows:
            return 0
        with self._cursor() as cursor:
            cursor.executemany(sql, rows)
            return cursor.rowcount

    # ----- 读 -----
    def fetch_all(self, sql: str, params: tuple | None = None) -> list[dict]:
        """查询，返回字典列表。"""
        with self._cursor(dict_cursor=True) as cursor:
            cursor.execute(sql, params or ())
            return list(cursor.fetchall())

    def close(self) -> None:
        """本实现的连接随用随关，预留接口以备将来切换。"""
        return None