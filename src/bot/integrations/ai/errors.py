# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>


class RepositorySummaryError(RuntimeError):
    __slots__ = ("original_error",)

    def __init__(self, original_error: BaseException | None = None) -> None:
        self.original_error = original_error
        super().__init__("Unable to generate repository summary with the configured models")


class NonAndroidProjectError(RuntimeError):
    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Repository is not an Android project: {reason}")


class PreviewEditError(RuntimeError):
    __slots__ = ("original_error",)

    def __init__(self, original_error: BaseException | None = None) -> None:
        self.original_error = original_error
        super().__init__("Unable to apply preview edits with the configured models")
