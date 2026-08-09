import re
from urllib.parse import unquote, urlsplit

from pydantic_ai import ModelRetry, RunContext

from androidrepo_bot.generation.schema import GeneratedOutput, GeneratedPost, MissingDownloadSource
from androidrepo_bot.generation.types import GenerationContext  # ruff: ignore[typing-only-first-party-import]
from androidrepo_bot.repositories.models import REPOSITORY_LINK_ID, RepositoryDetails

DRAFT_TEXT_BUDGET = 950

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_DOMAIN_LIKE_PATTERN = re.compile(
    r"(?<![a-z0-9-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?![a-z0-9-])", re.IGNORECASE
)
_URL_PATH_OR_QUERY_PATTERN = re.compile(r"[/\\?#=&:]")
_SUMMARY_OVERLAP_RATIO = 0.8
_SUMMARY_DUPLICATE_MINIMUM_TERMS = 2
_PLURAL_NORMALIZATION_MINIMUM_LENGTH = 4
_MINIMUM_SIGNIFICANT_TERM_LENGTH = 2
_STOPWORDS = frozenset({
    "about",
    "across",
    "also",
    "android",
    "app",
    "apps",
    "and",
    "are",
    "can",
    "for",
    "from",
    "has",
    "into",
    "its",
    "lets",
    "open",
    "project",
    "source",
    "that",
    "the",
    "their",
    "this",
    "through",
    "uses",
    "with",
    "without",
    "you",
})


def invalid_generated_link_ids(repository: RepositoryDetails, output: GeneratedPost) -> frozenset[str]:
    return frozenset(link.id for link in output.links if link.id not in repository.selectable_link_ids)


def has_valid_download_link(repository: RepositoryDetails, output: GeneratedPost) -> bool:
    return output.download_link_id is not None and output.download_link_id in repository.selectable_link_ids


def summary_redundant_features(output: GeneratedPost) -> tuple[str, ...]:
    normalized_summary = _normalized_text(output.summary)
    summary_terms = _meaningful_terms(output.summary)
    repeated: list[str] = []

    for feature in output.features:
        normalized_feature = _normalized_text(feature)
        feature_terms = _meaningful_terms(feature)
        if _contains_normalized_phrase(normalized_summary, normalized_feature) or _terms_repeat_summary(
            feature_terms, summary_terms
        ):
            repeated.append(feature)

    return tuple(repeated)


def literal_url_link_labels(repository: RepositoryDetails, output: GeneratedPost) -> tuple[str, ...]:
    literal_labels: list[str] = []
    for selected_link in output.links:
        verified_link = repository.link_by_id(selected_link.id)
        if verified_link is None:
            continue
        if _is_literal_url_label(selected_link.label, verified_link.url):
            literal_labels.append(selected_link.label)

    return tuple(literal_labels)


def generated_post_text_length(repository: RepositoryDetails, output: GeneratedPost) -> int:
    link_labels: list[str] = []
    repository_link = repository.link_by_id(REPOSITORY_LINK_ID)
    if repository_link is not None:
        link_labels.append(repository_link.label)

    link_labels.extend(link.label for link in output.links)
    hashtags = (f"#{tag.value}" for tag in output.tags)

    return sum(map(len, (output.project_name, output.summary, *output.features, *link_labels, *hashtags)))


def is_unchanged_slug(repository: RepositoryDetails, project_name: str) -> bool:
    raw_names = {repository.ref.name.strip(), repository.display_name.strip()}
    return project_name in raw_names and any(separator in project_name for separator in "-_.")


def _normalized_text(value: str) -> str:
    return " ".join(_TOKEN_PATTERN.findall(value.casefold()))


def _meaningful_terms(value: str) -> frozenset[str]:
    return frozenset(_normalize_term(token) for token in _TOKEN_PATTERN.findall(value.casefold()) if _is_term(token))


def _normalize_term(token: str) -> str:
    return token[:-1] if len(token) > _PLURAL_NORMALIZATION_MINIMUM_LENGTH and token.endswith("s") else token


def _is_term(token: str) -> bool:
    return len(token) > _MINIMUM_SIGNIFICANT_TERM_LENGTH and token not in _STOPWORDS


def _terms_repeat_summary(feature_terms: frozenset[str], summary_terms: frozenset[str]) -> bool:
    if len(feature_terms) < _SUMMARY_DUPLICATE_MINIMUM_TERMS:
        return False

    overlap = feature_terms & summary_terms
    return len(overlap) / len(feature_terms) >= _SUMMARY_OVERLAP_RATIO


def _contains_normalized_phrase(normalized_summary: str, normalized_feature: str) -> bool:
    return bool(normalized_feature and f" {normalized_feature} " in f" {normalized_summary} ")


def _is_literal_url_label(label: str, url: str) -> bool:
    normalized_label = label.strip().casefold()
    if _URL_PATH_OR_QUERY_PATTERN.search(normalized_label) or _DOMAIN_LIKE_PATTERN.search(normalized_label):
        return True

    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if not host:
        return False

    normalized_label_text = _normalized_text(label)
    host_text = _normalized_text(host)
    if normalized_label_text == host_text:
        return True

    path_text = _normalized_text(unquote(parsed.path))
    return bool(path_text and normalized_label_text == path_text)


def validate_generated_output(
    repository: RepositoryDetails, output: GeneratedPost, *, allow_missing_download: bool = False
) -> tuple[str, ...]:
    candidates = (
        _download_link_rule(repository, output, allow_missing_download=allow_missing_download),
        _selectable_link_ids_rule(repository, output),
        _text_budget_rule(repository, output),
        _summary_feature_redundancy_rule(output),
        _semantic_link_labels_rule(repository, output),
        _canonical_project_name_rule(repository, output),
    )
    return tuple(message for message in candidates if message is not None)


def validate_generated_post(ctx: RunContext[GenerationContext], output: GeneratedOutput) -> GeneratedOutput:
    if ctx.partial_output:
        return output

    if isinstance(output, MissingDownloadSource):
        if ctx.deps.allow_missing_download:
            msg = (
                "The user approved generation without a download source. Return return_post_draft with "
                "download_link_id set to null."
            )
            raise ModelRetry(msg)
        return output
    if not isinstance(output, GeneratedPost):
        return output

    messages = validate_generated_output(
        ctx.deps.repository, output, allow_missing_download=ctx.deps.allow_missing_download
    )
    if not messages:
        return output
    raise ModelRetry(_retry_message(messages))


def _download_link_rule(
    repository: RepositoryDetails, output: GeneratedPost, *, allow_missing_download: bool
) -> str | None:
    if has_valid_download_link(repository, output):
        return None

    if output.download_link_id is None:
        if allow_missing_download:
            return None
        return (
            "No download_link_id was selected. Return missing_download_source instead of a post draft when no official "
            "download source is available."
        )

    return (
        "Select download_link_id only from the supplied selectable link IDs. "
        f"Invalid download link ID: {output.download_link_id}."
    )


def _retry_message(messages: tuple[str, ...]) -> str:
    if len(messages) == 1:
        return messages[0]
    instructions = "; ".join(f"{index}. {message}" for index, message in enumerate(messages, start=1))
    return f"Fix all generated post validation issues: {instructions}"


def _selectable_link_ids_rule(repository: RepositoryDetails, output: GeneratedPost) -> str | None:
    invalid_link_ids = invalid_generated_link_ids(repository, output)
    if not invalid_link_ids:
        return None

    return (
        "Use only selectable link IDs from the supplied links evidence. "
        f"Invalid IDs: {', '.join(sorted(invalid_link_ids))}."
    )


def _text_budget_rule(repository: RepositoryDetails, output: GeneratedPost) -> str | None:
    text_length = generated_post_text_length(repository, output)
    if text_length <= DRAFT_TEXT_BUDGET:
        return None

    return (
        "Keep the combined project name, summary, features, resolved link "
        f"labels, and hashtags within {DRAFT_TEXT_BUDGET} characters. "
        f"The current content uses {text_length} characters. Shorten the "
        "summary or features, or select fewer links."
    )


def _summary_feature_redundancy_rule(output: GeneratedPost) -> str | None:
    redundant_features = summary_redundant_features(output)
    if not redundant_features:
        return None

    return (
        "Features must add information not already stated in the summary. "
        f"Rewrite or replace redundant features: {'; '.join(redundant_features)}."
    )


def _semantic_link_labels_rule(repository: RepositoryDetails, output: GeneratedPost) -> str | None:
    literal_labels = literal_url_link_labels(repository, output)
    if not literal_labels:
        return None

    return (
        "Link labels must be semantic destination names, not literal URL, "
        f"domain, host, path, or slug text. Rewrite these labels: {'; '.join(literal_labels)}."
    )


def _canonical_project_name_rule(repository: RepositoryDetails, output: GeneratedPost) -> str | None:
    if not is_unchanged_slug(repository, output.project_name):
        return None

    return (
        "Return the canonical public-facing project_name, not the unchanged "
        "repository slug. Use repository evidence to correct its spacing "
        "and capitalization while preserving intentional brand punctuation."
    )
