# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup


class PostStates(StatesGroup):
    waiting_for_repository_url = State()
    waiting_for_confirmation = State()
    previewing_post = State()


async def get_user_repository_url(state: FSMContext, user_id: int) -> str | None:
    data = await state.get_data()
    user_data = data.get(f"user_{user_id}", {})
    return user_data.get("repository_url")


async def update_user_data(state: FSMContext, user_id: int, **kwargs) -> None:
    data = await state.get_data()
    user_key = f"user_{user_id}"
    user_data = dict(data.get(user_key, {}))
    user_data.update(kwargs)
    await state.update_data({user_key: user_data})


async def clear_user_data(state: FSMContext, user_id: int) -> None:
    data = await state.get_data()
    user_key = f"user_{user_id}"
    if user_key in data:
        user_data = data[user_key]

        if banner_buffer := user_data.get("banner_buffer"):
            banner_buffer.close()

        data.pop(user_key)
        await state.set_data(data)

    if not any(key.startswith("user_") for key in data):
        await state.clear()
