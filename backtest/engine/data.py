"""回测数据加载。

复用 ``data_collection.storage.mysql.MysqlStorage``，避免与采集层抢连接池。
"""
from __future__ import annotations

import pandas as pd

from data_collection.storage.mysql import MysqlStorage
from config.settings import BACKTEST_STOCK_CODE, BACKTEST_START_DATE, BACKTEST_END_DATE


def load_stock_data(
    stock_code: str = BACKTEST_STOCK_CODE,
    start_date: str | None = BACKTEST_START_DATE,
    end_date: str | None = BACKTEST_END_DATE,
    storage: MysqlStorage | None = None,
) -> pd.DataFrame:
    """从 ``trade_stock_daily`` 加载日 K 线，返回 DataFrame。

    Parameters
    ----------
    stock_code : 股票代码，如 ``'600519.SH'``
    start_date : 开始日期 ``YYYY-MM-DD``（含），None 表示不限
    end_date   : 结束日期 ``YYYY-MM-DD``（含），None 表示不限
    storage    : 可选注入的存储对象；None 时新建（调用方负责 ``close``）

    Returns
    -------
    ``pandas.DataFrame``，索引为 ``trade_date``，列为
    ``open/high/low/close/volume``，已过滤掉 <=0 的无效价格（后复权异常值）。
    """
    own_storage = storage is None
    storage = storage or MysqlStorage()

    conditions = ["stock_code = %s"]
    params: list = [stock_code]
    if start_date:
        conditions.append("trade_date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("trade_date <= %s")
        params.append(end_date)

    sql = f"""
        SELECT trade_date, open_price, high_price, low_price, close_price, volume
        FROM trade_stock_daily
        WHERE {' AND '.join(conditions)}
        ORDER BY trade_date ASC
    """
    rows = storage.fetch_all(sql, tuple(params))
    if own_storage:
        storage.close()

    if not rows:
        raise ValueError(
            f"没有找到 {stock_code} 的数据，请检查数据库或先运行数据采集"
        )

    df = pd.DataFrame(rows)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df.set_index("trade_date", inplace=True)
    df.columns = ["open", "high", "low", "close", "volume"]
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 过滤无效价格（负价/零价多见于后复权异常），避免策略信号和收益计算错误
    valid = (df["open"] > 0) & (df["high"] > 0) & (df["low"] > 0) & (df["close"] > 0)
    df = df.loc[valid]
    if df.empty:
        raise ValueError(f"{stock_code} 过滤无效价格后无有效数据，请检查数据源")
    return df
