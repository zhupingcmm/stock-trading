"""策略注册与自动发现。

约定
----
每个策略模块（.py 文件）必须包含：

* ``STRATEGY_META``: 字典，键包括 ``name`` / ``category`` / ``desc`` /
  ``params`` / ``logic``，用于在 CLI 汇总/报告里展示策略元信息。
* ``Strategy`` 类：继承 ``backtrader.Strategy`` 的策略实现。

发现机制
--------
``backtest.strategies`` 包下的非 ``_`` 开头的 .py 文件视为内置策略；
``backtest.strategies.custom/`` 子目录下的 .py 文件视为用户自定义插件。
两个空间合并返回，文件名（去掉 .py）即 ``key``，供 CLI ``--strategy`` 使用。
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Iterable, Type

import backtrader as bt

CUSTOM_DIRNAME = "custom"


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    """动态 import 单文件模块；与 backtrader 的 MetaBase.__call__ 兼容。

    注意: 必须把模块注册进 sys.modules，否则 backtrader 用 ``cls.__module__``
    查 sys.modules 时会 KeyError。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载策略文件: {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _is_strategy_module(mod: ModuleType) -> bool:
    return bool(getattr(mod, "STRATEGY_META", None)) and bool(
        getattr(mod, "Strategy", None)
    )


def load_strategies(
    extra_dirs: Iterable[str | Path] | None = None,
) -> dict[str, dict]:
    """扫描内置 + ``custom/`` + 额外目录，返回 ``{key: {"meta": ..., "class": ...}}``。

    Parameters
    ----------
    extra_dirs : 用户指定的额外策略目录（绝对路径）
    """
    out: dict[str, dict] = {}

    # 1) 内置：backtest.strategies 包下的非 _ 开头 .py 文件（不含子包）
    pkg = importlib.import_module("backtest.strategies")
    # ``pkg.__path__`` 在不同 Python 版本下可能是 list / _NamespacePath，
    # 统一转成 list[str] 再传给 pathlib/iter_modules
    pkg_paths = [str(p) for p in list(getattr(pkg, "__path__", []))]  # type: ignore[arg-type]
    pkg_path = Path(pkg_paths[0]) if pkg_paths else None

    for info in pkgutil.iter_modules(pkg_paths):
        if info.name.startswith("_"):
            continue
        if info.ispkg:
            # 子目录（custom/）单独处理，不作为内置 key
            continue
        mod_name = f"{pkg.__name__}.{info.name}"
        mod = importlib.import_module(mod_name)
        if _is_strategy_module(mod):
            out[info.name] = {"meta": mod.STRATEGY_META, "class": mod.Strategy}

    # 2) custom/ 子目录
    if pkg_path and pkg_path.exists():
        custom_dir = pkg_path / CUSTOM_DIRNAME
        if custom_dir.is_dir():
            for py_file in sorted(custom_dir.glob("*.py")):
                if py_file.name.startswith("_"):
                    continue
                key = py_file.stem
                mod = _load_module_from_path(
                    f"{pkg.__name__}.{CUSTOM_DIRNAME}.{key}", py_file
                )
                if _is_strategy_module(mod):
                    out[key] = {"meta": mod.STRATEGY_META, "class": mod.Strategy}

    # 3) 用户额外目录
    for extra in extra_dirs or []:
        extra_path = Path(extra)
        if not extra_path.is_dir():
            continue
        for py_file in sorted(extra_path.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            key = py_file.stem
            mod = _load_module_from_path(f"user_strategy.{key}", py_file)
            if _is_strategy_module(mod):
                out[key] = {"meta": mod.STRATEGY_META, "class": mod.Strategy}

    return out


def get_strategy(key: str, extra_dirs: Iterable[str | Path] | None = None) -> Type[bt.Strategy]:
    """按 key 查找单个策略类。"""
    found = load_strategies(extra_dirs)
    if key not in found:
        available = ", ".join(sorted(found)) or "(none)"
        raise KeyError(f"未找到策略 '{key}'，可用: {available}")
    return found[key]["class"]
