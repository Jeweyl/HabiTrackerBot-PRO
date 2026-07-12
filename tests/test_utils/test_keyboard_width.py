"""Unit tests for inline keyboard width stabilization."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from src.keyboards.inline import get_checkin_keyboard, get_main_menu_keyboard
from src.utils.keyboard_width import (
    PAD_CHAR,
    TARGET_WIDTH,
    display_width,
    finalize_markup,
    pad_button_text,
    stabilize_markup,
    strip_button_padding,
)


class TestDisplayWidth:
    def test_ascii(self) -> None:
        assert display_width("Hello") == 5

    def test_empty(self) -> None:
        assert display_width("") == 0

    def test_emoji_counts_as_wide(self) -> None:
        # Common menu emoji should be wider than a single letter.
        assert display_width("✅") >= 2
        assert display_width("📋 Habits") > display_width("Habits")

    def test_pad_char_is_one(self) -> None:
        assert display_width(PAD_CHAR * 3) == 3


class TestPadButtonText:
    def test_pads_short_label_centered(self) -> None:
        padded = pad_button_text("OK", width=10)
        assert strip_button_padding(padded) == "OK"
        assert display_width(padded) == 10
        assert PAD_CHAR in padded
        # Centered: pad on both sides (even deficit → equal sides).
        assert padded.startswith(PAD_CHAR)
        assert padded.endswith(PAD_CHAR)

    def test_center_split_odd_deficit(self) -> None:
        # "A" width 1, target 6 → deficit 5 → left 2, right 3
        padded = pad_button_text("A", width=6)
        assert padded == PAD_CHAR * 2 + "A" + PAD_CHAR * 3
        assert display_width(padded) == 6

    def test_does_not_shrink_long_label(self) -> None:
        long = "X" * 40
        assert pad_button_text(long, width=10) == long

    def test_strips_existing_pad_before_reapply(self) -> None:
        once = pad_button_text("Hi", width=8)
        twice = pad_button_text(once, width=8)
        assert once == twice

    def test_strip_helper(self) -> None:
        assert strip_button_padding(f"{PAD_CHAR * 3}Menu{PAD_CHAR * 5}") == "Menu"



class TestStabilizeMarkup:
    def test_single_column_reaches_target(self) -> None:
        builder = InlineKeyboardBuilder()
        builder.button(text="A", callback_data="a")
        builder.button(text="BB", callback_data="b")
        builder.adjust(1)
        markup = finalize_markup(builder)
        for row in markup.inline_keyboard:
            assert len(row) == 1
            assert display_width(row[0].text or "") >= TARGET_WIDTH

    def test_preserves_callback_data(self) -> None:
        builder = InlineKeyboardBuilder()
        builder.button(text="Yes", callback_data="checkin:yes:1")
        builder.adjust(1)
        markup = finalize_markup(builder)
        assert markup.inline_keyboard[0][0].callback_data == "checkin:yes:1"
        assert strip_button_padding(markup.inline_keyboard[0][0].text) == "Yes"

    def test_multi_button_row_total_width(self) -> None:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="1", callback_data="1"),
                    InlineKeyboardButton(text="2", callback_data="2"),
                ]
            ]
        )
        out = stabilize_markup(markup, min_width=20)
        total = sum(display_width(b.text or "") for b in out.inline_keyboard[0])
        assert total >= 20

    def test_spacer_cells_not_inflated(self) -> None:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="01", callback_data="h:01"),
                    InlineKeyboardButton(text=" ", callback_data="ignore"),
                    InlineKeyboardButton(text="03", callback_data="h:03"),
                    InlineKeyboardButton(text="04", callback_data="h:04"),
                ]
            ]
        )
        out = stabilize_markup(markup, min_width=28)
        spacer = out.inline_keyboard[0][1]
        assert spacer.text == " "
        assert spacer.callback_data == "ignore"


class TestRealKeyboards:
    def test_main_menu_stable_width(self) -> None:
        kb = get_main_menu_keyboard("ru")
        widths = [
            display_width(btn.text or "")
            for row in kb.inline_keyboard
            for btn in row
        ]
        assert widths
        assert min(widths) >= TARGET_WIDTH
        # All single-column rows share the same target width.
        assert len(set(widths)) == 1

    def test_checkin_stable_width(self) -> None:
        kb = get_checkin_keyboard(1, "ru")
        for row in kb.inline_keyboard:
            assert len(row) == 1
            assert display_width(row[0].text or "") >= TARGET_WIDTH
            assert strip_button_padding(row[0].text or "")

    def test_main_menu_labels_still_readable(self) -> None:
        kb = get_main_menu_keyboard("ru")
        labels = [
            strip_button_padding(btn.text or "")
            for row in kb.inline_keyboard
            for btn in row
        ]
        assert "📋 Привычки" in labels
        assert "⚙️ Настройки" in labels
