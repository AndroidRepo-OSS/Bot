# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>


class RepositorySummaryError(RuntimeError):
    __slots__ = ("original_error",)

    def __init__(self, original_error: BaseException | None = None) -> None:
        self.original_error = original_error
        super().__init__("Unable to generate repository summary with the configured models")


class PreviewEditError(RuntimeError):
    __slots__ = ("original_error",)

    def __init__(self, original_error: BaseException | None = None) -> None:
        self.original_error = original_error
        super().__init__("Unable to apply preview edits with the configured models")
