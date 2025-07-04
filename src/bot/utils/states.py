# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram.fsm.state import State, StatesGroup


class PostStates(StatesGroup):
    waiting_for_repository_url = State()
    waiting_for_confirmation = State()
    previewing_post = State()
