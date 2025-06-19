# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import re

from aiogram.fsm.state import State, StatesGroup

REPOSITORY_URL_PATTERN = re.compile(r"^https?://(github\.com|gitlab\.com)/[\w.-]+/[\w.-]+/?$")


class PostStates(StatesGroup):
    waiting_for_repository_url = State()
    waiting_for_confirmation = State()
    previewing_post = State()
    editing_post = State()
    editing_description = State()
    editing_tags = State()
    editing_features = State()
    editing_links = State()
