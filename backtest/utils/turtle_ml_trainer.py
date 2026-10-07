"""海龟 ML 模型训练器。

来源：CASE-海龟交易法则/4-ML增强海龟策略.py

按时间分割训练 LightGBM / XGBoost / sklearn GradientBoosting：
  - 训练集：split_date 之前（含当天）
  - 测试集：split_date 之后

防过拟合：浅树 (max_depth=3) + 正则化 + 最小叶节点数。

依赖（按优先级）
----------------
1. lightgbm  —— 首选，小样本+结构化数据最优
2. xgboost   —— 次选
3. scikit-learn —— 保底（项目硬依赖）

如果三者都缺失，会抛出 ``MLEngineMissingError``，提示安装。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


class MLEngineMissingError(ImportError):
    """所有 ML 引擎都不可用时抛出。"""


@dataclass
class ModelMetrics:
    """模型评估指标。"""

    engine: str = ""
    train_size: int = 0
    test_size: int = 0
    train_positive_rate: float = 0.0
    test_positive_rate: float = 0.0
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    feature_importances: dict[str, float] = field(default_factory=dict)


def _try_lightgbm() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except ImportError:
        return False


def _try_xgboost() -> bool:
    try:
        import xgboost  # noqa: F401
        return True
    except ImportError:
        return False


def _try_sklearn() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


def detect_engine() -> str:
    """按优先级探测可用的 ML 引擎。

    返回值："lightgbm" / "xgboost" / "sklearn"。
    如果三者都不可用，**不抛错**，调用方应在 ``_build_model`` 时拿到错误。
    """
    if _try_lightgbm():
        return "lightgbm"
    if _try_xgboost():
        return "xgboost"
    if _try_sklearn():
        return "sklearn"
    return "none"


def _build_model(engine: str, y_train: np.ndarray):
    """按引擎构建分类器。无可用引擎时抛出 ``MLEngineMissingError``。"""
    if engine == "lightgbm":
        import lightgbm as lgb
        return lgb.LGBMClassifier(
            n_estimators=80, max_depth=3, learning_rate=0.1,
            min_child_samples=3, reg_alpha=0.1, reg_lambda=1.0,
            is_unbalance=True, verbose=-1, random_state=42,
        )
    if engine == "xgboost":
        import xgboost as xgb
        pos_weight = (y_train == 0).sum() / max(int((y_train == 1).sum()), 1)
        return xgb.XGBClassifier(
            n_estimators=80, max_depth=3, learning_rate=0.1,
            min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
            scale_pos_weight=pos_weight, eval_metric="logloss",
            verbosity=0, random_state=42,
        )
    if engine == "sklearn":
        from sklearn.ensemble import GradientBoostingClassifier
        return GradientBoostingClassifier(
            n_estimators=80, max_depth=3, learning_rate=0.1,
            min_samples_leaf=3, random_state=42,
        )
    raise MLEngineMissingError(
        "训练 ML 模型需要 lightgbm / xgboost / scikit-learn 之一。"
        "请安装至少一个：\n"
        "  pip install lightgbm\n"
        "  pip install xgboost\n"
        "  pip install scikit-learn"
    )


def train_model(
    features_df: pd.DataFrame,
    labels: np.ndarray,
    split_date: pd.Timestamp,
) -> tuple[object, ModelMetrics]:
    """按 split_date 时间分割训练模型。

    Parameters
    ----------
    features_df : 突破事件特征 DataFrame（索引为日期）
    labels      : 与 features_df 对齐的 0/1 标签
    split_date  : 训练/测试分割日期（之前训练，之后测试）

    Returns
    -------
    ``(model, metrics)``：训练好的模型对象 + 评估指标。
    若样本不足（训练<5 或 测试<3），返回 ``(None, ModelMetrics())``。
    若无 ML 引擎可用，抛出 ``MLEngineMissingError``。
    """
    engine = detect_engine()

    train_mask = features_df.index < split_date
    test_mask = features_df.index >= split_date

    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]
    X_train = features_df.iloc[train_idx]
    y_train = labels[train_idx]
    X_test = features_df.iloc[test_idx]
    y_test = labels[test_idx]

    metrics = ModelMetrics(
        engine=engine,
        train_size=len(X_train),
        test_size=len(X_test),
        train_positive_rate=float(y_train.mean()) if len(y_train) > 0 else 0.0,
        test_positive_rate=float(y_test.mean()) if len(y_test) > 0 else 0.0,
    )

    if len(X_train) < 5 or len(X_test) < 3:
        return None, metrics

    # 提前失败，避免跑到一半才发现
    model = _build_model(engine, y_train)
    model.fit(X_train, y_train)

    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score

    y_pred = model.predict(X_test)

    metrics.accuracy = float(accuracy_score(y_test, y_pred))
    metrics.precision = float(precision_score(y_test, y_pred, zero_division=0))
    metrics.recall = float(recall_score(y_test, y_pred, zero_division=0))
    metrics.f1 = float(f1_score(y_test, y_pred, zero_division=0))

    if hasattr(model, "feature_importances_"):
        imp = pd.Series(
            model.feature_importances_, index=features_df.columns,
        ).sort_values(ascending=False)
        mx = imp.max() if imp.max() > 0 else 1.0
        metrics.feature_importances = (imp / mx).to_dict()

    return model, metrics
