"""Source registry: every ``Source`` subclass in this package with an ``id``."""

from __future__ import annotations

import importlib
import pkgutil

from .base import Source


def all_sources() -> dict[str, type[Source]]:
    for mod in pkgutil.iter_modules(__path__):
        if mod.name != "base" and not mod.name.startswith("_"):
            importlib.import_module(f"{__name__}.{mod.name}")
    found: dict[str, type[Source]] = {}
    stack = list(Source.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        if cls.id:
            found[cls.id] = cls
    return dict(sorted(found.items()))
