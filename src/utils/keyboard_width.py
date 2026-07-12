"""Stabilize Telegram inline-keyboard width across screens.

Telegram sizes inline keyboards from message text and button labels.
There is no CSS width control, so short prompts make menus jump narrower
than long ones.  Padding labels with a non-collapsing blank (Braille
pattern blank) gives a consistent minimum width on all clients.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Braille pattern blank — survives Telegram's whitespace trimming better
# than regular / figure spaces on most clients.
PAD_CHAR = "\u2800"

# Target visual width in "character units" for a full-width row.
# Tuned for RU/EN menu labels with emoji without looking oversized.
TARGET_WIDTH = 28

# Characters treated as double-width for rough display estimation.
# Covers common emoji / symbols used in this bot's button labels.
_WIDE_RANGES = (
    (0x1F300, 0x1FAFF),  # Misc. emoji blocks
    (0x2600, 0x27BF),  # Misc symbols + dingbats
    (0xFE00, 0xFE0F),  # Variation selectors (skip width)
    (0x1F1E6, 0x1F1FF),  # Regional indicators (flags)
    (0x200D, 0x200D),  # ZWJ
)


def display_width(text: str) -> int:
    """Approximate rendered width of *text* for padding purposes.

    Emoji and most symbol-plane characters count as 2; combining marks and
    zero-width joiners count as 0; everything else as 1.  Good enough to
    keep menus visually aligned — not a full Unicode East-Asian width table.
    """
    if not text:
        return 0
    width = 0
    for ch in text:
        if ch == PAD_CHAR:
            width += 1
            continue
        cp = ord(ch)
        # Zero-width / combining
        if cp in (0x200D, 0xFE0E, 0xFE0F) or 0xFE00 <= cp <= 0xFE0F:
            continue
        if 0x0300 <= cp <= 0x036F:
            continue
        wide = any(start <= cp <= end for start, end in _WIDE_RANGES)
        width += 2 if wide else 1
    return width


def strip_button_padding(text: str) -> str:
    """Remove leading/trailing pad characters from a button label."""
    if not text:
        return text
    return text.strip(PAD_CHAR)


def pad_button_text(text: str, width: int = TARGET_WIDTH) -> str:
    """Center-pad *text* with :data:`PAD_CHAR` up to *width* display units.

    Extra space is split left/right so short labels sit near the middle of
    the button instead of hugging the left edge.  Labels already at or
    above *width* are returned unchanged (still stripped of accidental
    pads first for stability).
    """
    base = strip_button_padding(text) if text else " "
    if not base:
        base = " "
    current = display_width(base)
    if current >= width:
        return base
    deficit = width - current
    left = deficit // 2
    right = deficit - left
    return PAD_CHAR * left + base + PAD_CHAR * right



def stabilize_markup(
    markup: InlineKeyboardMarkup,
    min_width: int = TARGET_WIDTH,
) -> InlineKeyboardMarkup:
    """Return a copy of *markup* with rows padded to at least *min_width*.

    * Single-button rows: the button is padded to *min_width*.
    * Multi-button rows: each button is padded to ``min_width // n`` so the
      row roughly matches full-width menus without exploding grid cells.
    """
    if min_width < 1:
        return markup

    new_rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        if not row:
            new_rows.append([])
            continue

        n = len(row)
        if n == 1:
            btn = row[0]
            new_text = pad_button_text(btn.text or " ", min_width)
            new_rows.append([_with_text(btn, new_text)])
            continue

        per = max(1, min_width // n)
        new_row: list[InlineKeyboardButton] = []
        for btn in row:
            raw = btn.text if btn.text is not None else " "
            # Keep pure spacer cells (" ") short — they are layout fillers.
            if raw.strip() == "" and raw != PAD_CHAR:
                new_row.append(btn)
                continue
            new_row.append(_with_text(btn, pad_button_text(raw, per)))
        # If the row is still short (spacers / tiny labels), top up last button.
        total = sum(display_width(b.text or "") for b in new_row)
        if total < min_width and new_row:
            # Prefer topping up the last non-spacer button so the row
            # still reaches min_width without re-centering mid-label.
            deficit = min_width - total
            last = new_row[-1]
            new_row[-1] = _with_text(last, (last.text or "") + PAD_CHAR * deficit)
        new_rows.append(new_row)


    return InlineKeyboardMarkup(inline_keyboard=new_rows)


def finalize_markup(
    builder: InlineKeyboardBuilder,
    min_width: int = TARGET_WIDTH,
) -> InlineKeyboardMarkup:
    """Build markup from *builder* and apply width stabilization."""
    return stabilize_markup(builder.as_markup(), min_width=min_width)


def _with_text(btn: InlineKeyboardButton, text: str) -> InlineKeyboardButton:
    """Copy *btn* with a new label, preserving callback/url/etc."""
    return btn.model_copy(update={"text": text})
