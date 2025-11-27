# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import re

PREVIEW_PREFIX = "preview-"
PREVIEW_PATTERN = re.compile(rf"^{re.escape(PREVIEW_PREFIX)}([0-9a-fA-F]{{32}})$")


def build_preview_payload(submission_id: str) -> str:
    return f"{PREVIEW_PREFIX}{submission_id}"


def extract_submission_id(payload: str) -> str | None:
    if match := PREVIEW_PATTERN.match(payload):
        return match.group(1)
    return None
