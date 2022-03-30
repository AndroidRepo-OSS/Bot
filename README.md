# Android Repository - Telegram Bot

[![Codacy Badge](https://api.codacy.com/project/badge/Grade/025bfe51e380490695e8c0dd3c36a450)](https://app.codacy.com/gh/AmanoTeam/AndroidRepo?utm_source=github.com&utm_medium=referral&utm_content=AmanoTeam/AndroidRepo&utm_campaign=Badge_Grade_Settings)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![GitHub contributors](https://img.shields.io/github/contributors/AmanoTeam/AndroidRepo.svg)](https://GitHub.com/AmanoTeam/AndroidRepo/graphs/contributors/)

## Introduction

Android Repository Bot is a bot made for [@AndroidRepo](https://t.me/AndroidRepo) (Telegram channel), it was initially thought only to update the Magisk modules in the channel, but we will improve it over time.

> Developed in Python using the MTProto library [Pyrogram](https://github.com/pyrogram/pyrogram).

## How To Contribute

Every open source project lives from the
generous help by contributors that sacrifices
their time and `AndroidRepo` is no different.

### Instructions

1. Clone this Git repository locally: `git clone https://github.com/AmanoTeam/AndroidRepo`
2. Create a virtualenv (This step is optional, but highly recommended to avoid dependency conflicts)
   - `python3 -m venv .venv` (You don't need to run it again)
   - `. .venv/bin/activate` (You must run this every time you open the project in a new shell)
3. Install dependencies: `python3 -m pip install .`
   - Use `python3 -m pip install. [fast]` to install optional dependencies.
4. Create `config.py` from `config.py.example`: `cp config.py.example config.py`
5. Follow the instructions in the `config.py` file.
6. Start the bot: `python3 -m androidrepo`.

### Tools and tips

* Use [black](https://github.com/psf/black) and [isort](https://github.com/PyCQA/isort) (with black profile).
* Don't forget to add the [SPDX-License-Identifier](https://spdx.dev/ids/) header.
* Try to resolve any problems identified by our CI.

## License

[GPLv3](https://github.com/AmanoTeam/AndroidRepo/blob/main/LICENSE) © 2022 [AmanoTeam](https//github.com/AmanoTeam)
