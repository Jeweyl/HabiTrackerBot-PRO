"""Lightweight i18n helpers for HabiTracker UI strings.

Supported languages: ``ru`` (default), ``en``.
Missing keys fall back to Russian, then to the key itself — never raise.
"""

from __future__ import annotations

from typing import Any

from src.i18n import en as en_mod
from src.i18n import ru as ru_mod

_CATALOGS: dict[str, dict[str, str]] = {
    "ru": ru_mod.STRINGS,
    "en": en_mod.STRINGS,
}

_DEFAULT_LANG = "ru"
_SUPPORTED = frozenset(_CATALOGS.keys())


def normalize_lang(lang: str | None) -> str:
    """Return a supported language code; unknown values fall back to Russian."""
    if not lang:
        return _DEFAULT_LANG
    code = str(lang).strip().lower()
    if code in _SUPPORTED:
        return code
    # Accept values like "en-US" / "ru_RU"
    short = code.split("-", 1)[0].split("_", 1)[0]
    if short in _SUPPORTED:
        return short
    return _DEFAULT_LANG


class _SafeDict(dict):
    """dict subclass that leaves unknown format keys as ``{key}``."""

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return "{" + key + "}"


def t(key: str, lang: str | None = "ru", **kwargs: Any) -> str:
    """Translate *key* for *lang*, with safe fallbacks.

    Lookup order:
    1. catalog for normalized *lang*
    2. Russian catalog
    3. the raw *key* string

    ``**kwargs`` are interpolated via ``str.format_map`` with a safe dict
    so missing placeholders never raise. Invalid format strings return the
    template as-is.
    """
    code = normalize_lang(lang)
    catalog = _CATALOGS.get(code, _CATALOGS[_DEFAULT_LANG])
    template = catalog.get(key)
    if template is None and code != _DEFAULT_LANG:
        template = _CATALOGS[_DEFAULT_LANG].get(key)
    if template is None:
        template = key

    if not kwargs:
        return template

    try:
        return template.format_map(_SafeDict(kwargs))
    except (ValueError, TypeError):
        return template


__all__ = ["t", "normalize_lang"]
