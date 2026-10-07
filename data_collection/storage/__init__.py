"""存储层。

支持 csv / parquet / sqlite / postgres 等多种后端，
为上层提供统一的读写接口。
"""
from data_collection.storage.mysql import MysqlStorage

__all__ = ["MysqlStorage"]