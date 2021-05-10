# This file is part of AndroidRepo (Telegram Bot)
# Copyright (C) 2021 AmanoTeam

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import glob
import importlib
import logging
from types import ModuleType
from typing import List

modules: List[ModuleType] = []
log = logging.getLogger(__name__)


def load(bot):
    files = glob.glob("androidrepo/handlers/**/*.py", recursive=True)
    main_dir = sorted(
        [*filter(lambda file: len(file.split("/")) == 3, files)],
        key=lambda file: file.split("/")[2],
    )
    sub_dirs = sorted(
        [*filter(lambda file: len(file.split("/")) >= 4, files)],
        key=lambda file: file.split("/")[3],
    )
    files = main_dir + sub_dirs

    for file_name in files:
        try:
            module = importlib.import_module(
                file_name.replace("/", ".").replace(".py", "")
            )
            modules.append(module)
        except BaseException:
            log.error("Failed to import the module: %s", file_name, exc_info=True)
            continue

        functions = [*filter(callable, module.__dict__.values())]
        functions = [
            *filter(lambda function: hasattr(function, "handlers"), functions),
        ]

        for function in functions:
            for handler in function.handlers:
                bot.add_handler(*handler)

    log.info(
        "%s module%s imported successfully!",
        len(modules),
        "s" if len(modules) != 1 else "",
    )


def reload(bot):
    for index, module in enumerate(modules):
        functions = [*filter(callable, module.__dict__.values())]
        functions = [
            *filter(lambda function: hasattr(function, "handlers"), functions),
        ]

        for function in functions:
            for handler in function.handlers:
                bot.remove_handler(*handler)

        module = importlib.reload(module)
        modules[index] = module

        functions = [*filter(callable, module.__dict__.values())]
        functions = [
            *filter(lambda function: hasattr(function, "handlers"), functions),
        ]

        for function in functions:
            for handler in function.handlers:
                bot.add_handler(*handler)

    log.info(
        "%s module%s reloaded successfully!",
        len(modules),
        "s" if len(modules) != 1 else "",
    )
