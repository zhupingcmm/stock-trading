"""回测工具子包。

非策略相关的辅助模块（特征工程 / 模型训练 / 通用工具等）。
"""
from backtest.utils.turtle_ml_features import (
    FEATURE_COLS,
    collect_multi_stock_features,
    compute_features,
    generate_predictions,
)
from backtest.utils.turtle_ml_trainer import (
    MLEngineMissingError,
    ModelMetrics,
    detect_engine,
    train_model,
)

__all__ = [
    "FEATURE_COLS",
    "MLEngineMissingError",
    "ModelMetrics",
    "collect_multi_stock_features",
    "compute_features",
    "detect_engine",
    "generate_predictions",
    "train_model",
]
