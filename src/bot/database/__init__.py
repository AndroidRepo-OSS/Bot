# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from .connection import db_manager
from .models import AppSubmission, ScheduledPost
from .operations import (
    can_submit_app,
    cleanup_old_published_posts,
    cleanup_orphaned_scheduled_posts,
    get_last_post_time,
    get_next_available_slot_with_lock,
    get_scheduled_posts_after_time,
    get_scheduled_posts_in_range,
    has_pending_scheduled_post,
    schedule_post,
    submit_app,
    update_scheduled_post_as_published,
    update_scheduled_post_time,
)

__all__ = (
    "AppSubmission",
    "ScheduledPost",
    "can_submit_app",
    "cleanup_old_published_posts",
    "cleanup_orphaned_scheduled_posts",
    "db_manager",
    "get_last_post_time",
    "get_next_available_slot_with_lock",
    "get_scheduled_posts_after_time",
    "get_scheduled_posts_in_range",
    "has_pending_scheduled_post",
    "schedule_post",
    "submit_app",
    "update_scheduled_post_as_published",
    "update_scheduled_post_time",
)
