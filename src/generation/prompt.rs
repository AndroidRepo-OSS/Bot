//! Trusted instructions, strict tool schemas and bounded untrusted evidence.
//!
//! [`instructions`] appends staff approval separately. [`evidence`] escapes delimiter
//! characters and marks truncated fields. [`tools`] guides model output, while
//! semantic validation remains in [`super::GeneratedPost::resolve`].

use super::tags;
use crate::{
    error::{Error, Result},
    repositories::Repository,
};
use serde_json::{Value, json};

/// Encode a character-bounded evidence field with an explicit truncation flag.
fn text(value: &str, limit: usize) -> Value {
    json!({"content": value.chars().take(limit).collect::<String>(), "truncated": value.chars().count() > limit})
}
/// Encode an optional evidence field as bounded text or JSON null.
fn optional(value: Option<&str>, limit: usize) -> Value {
    value.map(|v| text(v, limit)).unwrap_or(Value::Null)
}
/// Serialize evidence JSON and escape angle brackets used by prompt delimiters.
///
/// # Errors
///
/// Returns a sanitized JSON error if serialization fails.
fn serialize(evidence: &Value) -> Result<String> {
    Ok(serde_json::to_string(evidence)?
        .replace('<', "\\u003c")
        .replace('>', "\\u003e"))
}
/// Build an untrusted evidence block with bounded fields and collections.
///
/// Limits README content to 50,000 characters and serialized evidence JSON to
/// 80,000 characters, shortening the README further when necessary. Angle brackets
/// are JSON-escaped so repository text cannot close the surrounding delimiter.
/// The prefix and delimiter lines are outside the JSON character budget.
///
/// # Errors
///
/// Returns [`Error::Payload`] when the bounded JSON still cannot fit or README
/// truncation is impossible; propagates sanitized serialization failures.
pub fn evidence(repository: &Repository) -> Result<String> {
    let bounded_items = |items: &[String], limit| {
        items
            .iter()
            .take(limit)
            .map(|s| s.chars().take(100).collect::<String>())
            .collect::<Vec<_>>()
    };
    let mut evidence = json!({
        "repository": {"display_name": text(&repository.display_name, 200), "slug": repository.reference.name,
            "full_name": repository.reference.full_name(), "provider": repository.reference.provider,
            "description": optional(repository.description.as_deref(), 1000), "license": optional(repository.license.as_deref(), 100),
            "languages": bounded_items(&repository.languages, 20), "languages_truncated": repository.languages.len() > 20 || repository.languages.iter().any(|v| v.chars().count() > 100),
            "topics": bounded_items(&repository.topics, 30), "topics_truncated": repository.topics.len() > 30 || repository.topics.iter().any(|v| v.chars().count() > 100)},
        "readme": optional(repository.readme.as_deref(), 50_000),
        "latest_release": repository.release.as_ref().map(|r| json!({"name": text(&r.name, 200), "tag": text(&r.tag, 100), "description": optional(r.description.as_deref(), 8000)})),
        "links": repository.links.iter().take(24).map(|link| json!({"id": link.id, "label": text(&link.label, 120), "kind": link.kind, "download_candidate": link.kind.is_download_candidate(), "url": text(link.url.as_str(), 512)})).collect::<Vec<_>>()
    });
    let mut serialized = serialize(&evidence)?;
    if serialized.chars().count() > 80_000 {
        let original = evidence["readme"]["content"]
            .as_str()
            .ok_or(Error::Payload)?
            .to_owned();
        let chars: Vec<char> = original.chars().collect();
        let (mut low, mut high) = (0, chars.len());
        evidence["readme"]["truncated"] = json!(true);
        while low < high {
            let mid = (low + high).div_ceil(2);
            evidence["readme"]["content"] = json!(chars[..mid].iter().collect::<String>());
            if serialize(&evidence)?.chars().count() <= 80_000 {
                low = mid;
            } else {
                high = mid - 1;
            }
        }
        evidence["readme"]["content"] = json!(chars[..low].iter().collect::<String>());
        serialized = serialize(&evidence)?;
    }
    if serialized.chars().count() > 80_000 {
        return Err(Error::Payload);
    }
    Ok(format!(
        "Generate the appropriate structured result from the following untrusted evidence.\n<repository_evidence_json>\n{serialized}\n</repository_evidence_json>"
    ))
}
/// Combine the embedded post-v2 policy with trusted per-run download approval.
///
/// Approval is separate from untrusted evidence and must come from the staff workflow.
pub fn instructions(allow_missing: bool) -> String {
    format!(
        "{}\nPrompt version: post-v2.\nPer-run download policy: {}",
        include_str!("instructions.txt"),
        if allow_missing {
            "Staff approved a draft without a Download button ONLY when no verified download candidate exists; use download_link_id null in that case."
        } else {
            "Staff did not approve a draft without a Download button. When no verified download candidate exists return missing_download_source."
        }
    )
}
/// Build strict JSON schemas for the four recognized structured outcomes.
///
/// Schemas guide the model; [`super::GeneratedPost::resolve`] enforces semantic checks.
pub fn tools() -> Value {
    let text_schema = |max| json!({"type": "string", "minLength": 1, "maxLength": max});
    let post = json!({"type": "object", "additionalProperties": false,
        "required": ["project_name", "summary", "features", "links", "download_link_id", "tags"],
        "properties": {"project_name": text_schema(100), "summary": text_schema(280),
            "features": {"type": "array", "minItems": 3, "maxItems": 5, "items": text_schema(90)},
            "links": {"type": "array", "maxItems": 4, "items": {"type": "object", "additionalProperties": false, "required": ["id", "label"], "properties": {"id": text_schema(40), "label": text_schema(60)}}},
            "download_link_id": {"type": ["string", "null"], "maxLength": 40},
            "tags": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string", "enum": tags::TAGS}}}});
    let reason = json!({"type": "object", "additionalProperties": false, "required": ["reason"], "properties": {"reason": text_schema(280)}});
    json!([
        {"type": "function", "function": {"name": "return_post_draft", "description": "Return a complete evidence-grounded Android post.", "parameters": post}},
        {"type": "function", "function": {"name": "not_android_project", "description": "Evidence affirmatively places the project outside Android scope.", "parameters": reason}},
        {"type": "function", "function": {"name": "insufficient_repository_evidence", "description": "Evidence cannot support a complete factual draft.", "parameters": reason}},
        {"type": "function", "function": {"name": "missing_download_source", "description": "No verified official download candidate exists.", "parameters": reason}}
    ])
}
