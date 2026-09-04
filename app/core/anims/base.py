"""动画层基类、参数 schema 与注册表（策略模式）。

新增动画 = 写 1 个 BaseLayer 子类 + @register 装饰 1 行；GUI 下拉框与参数控件按
params_schema 自动生成，不得在 GUI 写死动画参数。
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from ..context import RenderContext

KIND_BACKGROUND = "background"
KIND_LYRICS = "lyrics"
KIND_COVER = "cover"
KINDS = (KIND_BACKGROUND, KIND_LYRICS, KIND_COVER)


@dataclass(frozen=True)
class ParamSpec:
    """动画参数描述：GUI 据此生成控件，kproj 按 key 存取 params。"""

    key: str
    label: str
    kind: str  # "int" | "float" | "bool" | "choice"
    default: Any
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = ()


# 注册表：kind → {anim_type → layer 类}
ANIM_REGISTRY: dict[str, dict[str, type[BaseLayer]]] = {k: {} for k in KINDS}


def register(kind: str) -> Callable[[type[BaseLayer]], type[BaseLayer]]:
    """类装饰器：把动画层注册进 ANIM_REGISTRY。"""

    def decorator(cls: type[BaseLayer]) -> type[BaseLayer]:
        ANIM_REGISTRY[kind][cls.anim_type] = cls
        return cls

    return decorator


def layer_class(kind: str, anim_type: str) -> type[BaseLayer] | None:
    """查注册表；未知 anim_type 回退该 kind 的首个注册项（向前兼容）。"""
    table = ANIM_REGISTRY.get(kind)
    if not table:
        return None
    return table.get(anim_type) or next(iter(table.values()), None)


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


class BaseLayer(ABC):
    """动画层：prepare（光栅化，仅参数/资源变化时）与 eval（纯状态）分离。"""

    kind: ClassVar[str]
    anim_type: ClassVar[str]
    label: ClassVar[str]

    def __init__(self, params: dict | None = None) -> None:
        self.params: dict[str, Any] = self.resolve_params(params or {})

    @classmethod
    def params_schema(cls) -> list[ParamSpec]:
        """供 GUI 生成控件、kproj 存 params。默认无额外参数。"""
        return []

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        return {spec.key: spec.default for spec in cls.params_schema()}

    @classmethod
    def resolve_params(cls, params: dict) -> dict[str, Any]:
        """按 schema 收敛：未知 key 忽略，非法值回退默认，越界钳制。"""
        if not isinstance(params, dict):
            params = {}
        resolved = cls.defaults()
        for spec in cls.params_schema():
            if spec.key not in params:
                continue
            raw = params[spec.key]
            try:
                # 类型收敛与钳制必须在 try 内：kproj params 来自外部 JSON
                if spec.kind == "int":
                    if isinstance(raw, bool):
                        continue
                    value: Any = round(float(raw))
                    if not math.isfinite(value):
                        continue
                elif spec.kind == "float":
                    if isinstance(raw, bool):
                        continue
                    value = float(raw)
                    if not math.isfinite(value):
                        continue
                elif spec.kind == "bool":
                    if isinstance(raw, bool):
                        value = raw
                    elif isinstance(raw, (int, float)) and math.isfinite(raw):
                        value = bool(raw)
                    elif isinstance(raw, str):
                        normalized = raw.strip().lower()
                        if normalized in {"true", "1", "yes", "on"}:
                            value = True
                        elif normalized in {"false", "0", "no", "off"}:
                            value = False
                        else:
                            continue
                    else:
                        continue
                elif spec.kind == "choice":
                    value = str(raw)
                    if spec.choices and value not in spec.choices:
                        continue
                else:
                    continue
                if not isinstance(value, bool) and spec.min is not None:
                    value = max(spec.min, value)
                if not isinstance(value, bool) and spec.max is not None:
                    value = min(spec.max, value)
                if spec.kind == "int":
                    value = round(value)
            except (TypeError, ValueError):
                continue
            resolved[spec.key] = value
        return resolved

    @abstractmethod
    def prepare(self, ctx: RenderContext) -> object:
        """光栅化图层资源（Pillow/NumPy），结果由 Scene 缓存进 ctx.assets。"""

    @abstractmethod
    def eval(self, t: float, ctx: RenderContext) -> object:
        """纯函数：t → 图层状态（透明度/位移/角度），不碰像素。"""
