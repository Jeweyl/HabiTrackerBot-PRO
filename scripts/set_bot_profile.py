#!/usr/bin/env python3
"""Apply or inspect Telegram bot profile (description, about, commands).

Uses BOT_TOKEN from environment / .env via ``src.config.settings``.
Does not upload avatar — set photo via BotFather manually.

Usage (from repo root)::

    python scripts/set_bot_profile.py              # apply all locales
    python scripts/set_bot_profile.py --dry-run    # print only
    python scripts/set_bot_profile.py --show       # fetch current from API
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow running as ``python scripts/set_bot_profile.py`` without install.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from aiogram import Bot
from aiogram.types import BotCommand

from src.bot_profile.texts import ABOUT, COMMANDS, DESCRIPTIONS, validate_profile_texts
from src.config import settings

# Locales to publish: default (None) + explicit RU/EN.
_LOCALES: tuple[str | None, ...] = (None, "ru", "en")


def _lang_label(code: str | None) -> str:
    return "default" if code is None else code


async def apply_profile(bot: Bot, *, dry_run: bool) -> None:
    """Set description, short description and commands for all locales."""
    validate_profile_texts()

    for lang in _LOCALES:
        desc = DESCRIPTIONS[lang]
        about = ABOUT[lang]
        cmds = [
            BotCommand(command=c, description=d) for c, d in COMMANDS[lang]
        ]
        label = _lang_label(lang)

        print(f"\n=== {label} ===")
        print(f"description ({len(desc)} chars):\n{desc}\n")
        print(f"about ({len(about)} chars): {about}")
        print("commands:", ", ".join(f"/{c.command}" for c in cmds))

        if dry_run:
            continue

        kwargs: dict = {}
        if lang is not None:
            kwargs["language_code"] = lang

        await bot.set_my_description(description=desc, **kwargs)
        await bot.set_my_short_description(short_description=about, **kwargs)
        await bot.set_my_commands(cmds, **kwargs)
        print(f"OK applied ({label})")


async def show_profile(bot: Bot) -> None:
    """Print current profile fields from Telegram API."""
    for lang in _LOCALES:
        kwargs: dict = {}
        if lang is not None:
            kwargs["language_code"] = lang
        label = _lang_label(lang)

        desc = await bot.get_my_description(**kwargs)
        about = await bot.get_my_short_description(**kwargs)
        cmds = await bot.get_my_commands(**kwargs)

        print(f"\n=== {label} (live) ===")
        print("description:", desc.description or "(empty)")
        print("about:", about.short_description or "(empty)")
        if cmds:
            for c in cmds:
                print(f"  /{c.command} — {c.description}")
        else:
            print("  commands: (none)")


async def _run(args: argparse.Namespace) -> int:
    if not settings.BOT_TOKEN:
        print("ERROR: BOT_TOKEN is not set", file=sys.stderr)
        return 1

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        if args.show:
            await show_profile(bot)
        else:
            await apply_profile(bot, dry_run=args.dry_run)
            if args.dry_run:
                print("\n(dry-run: nothing sent to Telegram)")
    finally:
        await bot.session.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set HabiTracker bot description/about/commands via Bot API",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print texts and lengths without calling Telegram",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Fetch and print current profile from Telegram",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
