from __future__ import annotations

from importlib import import_module

from feedsmith.sources.base import SourceAdapter


def load_adapter(name: str) -> type[SourceAdapter]:
    """Load ``feedsmith.sources.<name>`` without changing the CLI for new sources."""
    if not name.isidentifier():
        raise ValueError(f"invalid source adapter name {name!r}")
    try:
        module = import_module(f"feedsmith.sources.{name}")
    except ModuleNotFoundError as error:
        if error.name == f"feedsmith.sources.{name}":
            raise ValueError(f"no adapter is installed for source {name!r}") from error
        raise
    adapter = getattr(module, "SOURCE_ADAPTER", None)
    if not isinstance(adapter, type) or not issubclass(adapter, SourceAdapter):
        raise ValueError(f"source adapter {name!r} must export SOURCE_ADAPTER")
    return adapter
