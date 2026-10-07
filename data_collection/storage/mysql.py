"""MySQL 存储后端。

与参考脚本 ``db_config.py`` 同样的 ``WUCAI_SQL_*`` 环境变量命名，
便于直接复用项目根 ``.env``。
"""
from __future__ import annotations

import random
import time
from contextlib import contextmanager
from typing import Iterator

import pymysql
from pymysql.cursors import DictCursor

from config.settings import MYSQL_CONFIG, MySQLConfig

# MySQL 可重试错误码：
#  1213 ER_LOCK_DEADLOCK  — 死锁，官方建议重试事务
#  1205 ER_LOCK_WAIT_TIMEOUT — 锁等待超时
_RETRYABLE_MYSQL_ERRNOS = {1213, 1205}
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 0.05  # 50ms，叠加随机抖动避免锁步重试


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
        """单条 UPDATE/INSERT，返回受影响行数。

        死锁/锁等待超时自动重试：InnoDB 在并发写入带 UNIQUE KEY 的表时
        偶尔触发 1213/1205，官方建议重试整个事务。
        """
        return self._with_retry(lambda cur: cur.execute(sql, params or (())))

    def executemany(self, sql: str, rows: list[tuple]) -> int:
        """批量 UPSERT，返回受影响行数。空列表直接返回 0。

        死锁/锁等待超时自动重试：见 ``execute``。
        """
        if not rows:
            return 0
        return self._with_retry(lambda cur: cur.executemany(sql, rows))

    # ----- 重试工具 -----
    def _with_retry(self, op):
        """在 ``_cursor`` 上下文内执行 ``op(cursor)``，遇可重试错误时整事务重试。

        pymysql 的 ``execute``/``executemany`` 都直接返回 rowcount。
        """
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                with self._cursor() as cursor:
                    return op(cursor)
            except pymysql.err.OperationalError as exc:
                errno = exc.args[0] if exc.args else None
                if errno not in _RETRYABLE_MYSQL_ERRNOS:
                    raise
                last_exc = exc
                # 抖动退避，避免多线程锁步重试引发新死锁
                delay = _RETRY_BASE_DELAY * (attempt + 1) + random.uniform(0, 0.05)
                time.sleep(delay)
        # 全部重试失败后，把最后一次的异常抛上去
        assert last_exc is not None
        raise last_exc

    # ----- 读 -----
    def fetch_all(self, sql: str, params: tuple | None = None) -> list[dict]:
        """查询，返回字典列表。"""
        with self._cursor(dict_cursor=True) as cursor:
            cursor.execute(sql, params or ())
            return list(cursor.fetchall())

    def close(self) -> None:
        """本实现的连接随用随关，预留接口以备将来切换。"""
        return None