# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import os

from tortoise import Tortoise, fields
from tortoise.models import Model


class Contact(Model):
    id = fields.IntField(pk=True)
    user = fields.IntField()


class Modules(Model):
    id = fields.CharField(pk=True, max_length=255)
    url = fields.TextField()
    name = fields.TextField()
    version = fields.TextField()
    version_code = fields.IntField()
    last_update = fields.IntField()


class Magisk(Model):
    branch = fields.TextField(pk=True)
    version = fields.TextField()
    version_code = fields.IntField()
    link = fields.TextField()
    note = fields.TextField()
    changelog = fields.TextField()


class Requests(Model):
    id = fields.IntField(pk=True)
    user = fields.IntField()
    time = fields.IntField()
    ignore = fields.IntField()
    request = fields.TextField()
    attempts = fields.IntField()
    request_id = fields.IntField()
    message_id = fields.IntField()


async def connect_database():
    await Tortoise.init(
        {
            "connections": {
                "bot_db": os.getenv(
                    "DATABASE_URL", "sqlite://androidrepo/database/database.sqlite"
                )
            },
            "apps": {"bot": {"models": [__name__], "default_connection": "bot_db"}},
        }
    )
    # Generate the schema
    await Tortoise.generate_schemas()
