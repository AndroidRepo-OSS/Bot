# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.modules.posts.callbacks import (
    EditAction,
    EditCallback,
    EditField,
    PostAction,
    PostCallback,
)

from .models import KeyboardType

ButtonConfig = tuple[str, PostCallback | EditCallback]


def create_keyboard(keyboard_type: KeyboardType) -> InlineKeyboardMarkup:
    buttons = _get_keyboard_buttons(keyboard_type)
    button_layout = _get_keyboard_layout(keyboard_type)

    return _build_keyboard(buttons, button_layout)


def _get_keyboard_buttons(keyboard_type: KeyboardType) -> list[ButtonConfig]:
    button_configs = {
        KeyboardType.CONFIRMATION: _get_confirmation_buttons(),
        KeyboardType.PREVIEW: _get_preview_buttons(),
        KeyboardType.EDIT: _get_edit_buttons(),
        KeyboardType.BACK_TO_EDIT: _get_back_to_edit_buttons(),
    }

    return button_configs[keyboard_type]


def _get_confirmation_buttons() -> list[ButtonConfig]:
    return [
        ("✅ Confirm", PostCallback(action=PostAction.CONFIRM)),
        ("❌ Cancel", PostCallback(action=PostAction.CANCEL)),
    ]


def _get_preview_buttons() -> list[ButtonConfig]:
    return [
        ("✅ Publish", PostCallback(action=PostAction.PUBLISH)),
        ("✏️ Edit", PostCallback(action=PostAction.EDIT)),
        ("🔄 Regenerate", PostCallback(action=PostAction.REGENERATE)),
        ("❌ Cancel", PostCallback(action=PostAction.CANCEL)),
    ]


def _get_edit_buttons() -> list[ButtonConfig]:
    return [
        ("📝 Description", EditCallback(action=EditAction.FIELD, field=EditField.DESCRIPTION)),
        ("🏷️ Tags", EditCallback(action=EditAction.FIELD, field=EditField.TAGS)),
        ("⭐ Features", EditCallback(action=EditAction.FIELD, field=EditField.FEATURES)),
        ("🔗 Links", EditCallback(action=EditAction.FIELD, field=EditField.LINKS)),
        ("🔙 Back", PostCallback(action=PostAction.BACK_TO_PREVIEW)),
        ("❌ Cancel", PostCallback(action=PostAction.CANCEL)),
    ]


def _get_back_to_edit_buttons() -> list[ButtonConfig]:
    return [
        ("🔙 Back", EditCallback(action=EditAction.BACK_TO_MENU)),
    ]


def _get_keyboard_layout(keyboard_type: KeyboardType) -> tuple[int, ...]:
    layouts = {
        KeyboardType.CONFIRMATION: (2,),
        KeyboardType.PREVIEW: (2, 2),
        KeyboardType.EDIT: (2, 2, 2),
        KeyboardType.BACK_TO_EDIT: (1,),
    }

    return layouts[keyboard_type]


def _build_keyboard(buttons: list[ButtonConfig], layout: tuple[int, ...]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for text, callback_data in buttons:
        builder.button(text=text, callback_data=callback_data)

    builder.adjust(*layout)
    return builder.as_markup()
