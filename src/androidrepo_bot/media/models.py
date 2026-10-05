"""Bounded values shared by the artwork loader and banner renderer."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, field_validator


def _normalize_text(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


def _empty_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


type Text = Annotated[str, BeforeValidator(_normalize_text), StringConstraints(min_length=1)]
type Metadata = Annotated[Annotated[Text, Field(max_length=200)] | None, BeforeValidator(_empty_to_none)]
type Topic = Annotated[str, BeforeValidator(_normalize_text), StringConstraints(max_length=100)]


class _MediaModel(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")


class BannerRequest(_MediaModel):
    project_name: Text = Field(max_length=200)
    repository: Text = Field(max_length=300)
    provider: Text = Field(max_length=50)
    primary_language: Metadata = None
    license_name: Metadata = None
    release: Metadata = None
    topics: tuple[Topic, ...] = Field(default=(), max_length=20)

    @field_validator("topics")
    @classmethod
    def omit_empty_topics(cls, topics: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(topic for topic in topics if topic)


class SpaceArtwork(_MediaModel):
    content: bytes = Field(min_length=1)
    identifier: Text = Field(max_length=200)
    title: Text = Field(max_length=500)
    center: Text = Field(max_length=200)
    date_created: Annotated[Annotated[Text, Field(max_length=100)] | None, BeforeValidator(_empty_to_none)]
    credit: Text = Field(max_length=300)


class BannerImage(_MediaModel):
    content: bytes = Field(min_length=1)
    filename: Text = Field(max_length=255)
    artwork_id: Text = Field(max_length=200)
