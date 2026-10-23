//! Bounded Chat Completions tool-call generation and corrective requests.
//!
//! [`generate`] limits total deadline, requests, response bytes and output tokens.
//! Only one recognized tool call is accepted; free-form output never becomes a post.

use super::{GeneratedPost, Outcome, Reason, prompt, validate_plain_text};
use crate::{
    config::Config,
    error::{Error, Result},
    http,
    repositories::Repository,
};
use reqwest::Client;
use serde::Deserialize;
use serde_json::json;
use std::time::Duration;

/// Chat Completions envelope consumed by structured output validation.
#[derive(Deserialize)]
struct Response {
    /// Must contain exactly one model choice.
    choices: Vec<Choice>,
    /// Optional usage; missing usage conservatively consumes 2,048 tokens.
    usage: Option<Usage>,
}
/// Provider-reported output token usage used to bound the complete run.
#[derive(Deserialize)]
struct Usage {
    /// Output token count added to the 6,144-token run budget.
    completion_tokens: u64,
}
/// One model choice and its termination reason.
#[derive(Deserialize)]
struct Choice {
    /// Assistant message expected to contain exactly one tool call.
    message: Message,
    /// Length termination is rejected as incomplete output.
    finish_reason: Option<String>,
}
/// Assistant tool calls; free-form assistant text is not accepted as a result.
#[derive(Deserialize)]
struct Message {
    /// Structured outputs; absent calls become an empty list and fail validation.
    #[serde(default)]
    tool_calls: Vec<Call>,
}
/// Tool invocation containing the selected function and encoded arguments.
#[derive(Deserialize)]
struct Call {
    /// Selected tool and JSON-encoded arguments.
    function: Function,
}
/// Function name and JSON argument string from the provider.
#[derive(Deserialize)]
struct Function {
    /// Must name one of the four declared output tools.
    name: String,
    /// JSON string decoded using a strict post or reason schema.
    arguments: String,
}

/// Request a structured draft or refusal within a 120-second total deadline.
///
/// Uses at most three requests, each with 2,048 output tokens, and a 6,144-token
/// aggregate budget. Corrective requests follow invalid output, not arbitrary HTTP
/// failures. `allow_missing` must reflect staff approval, never repository text.
/// This contacts the configured model provider and may consume billed tokens.
///
/// # Errors
///
/// Returns [`Error::Timeout`] on the total deadline, sanitized HTTP/JSON/payload
/// errors on failed reads, or [`Error::Generation`] for rejected status/output/budget.
pub async fn generate(
    client: &Client,
    config: &Config,
    repository: &Repository,
    allow_missing: bool,
) -> Result<Outcome> {
    tokio::time::timeout(
        Duration::from_secs(120),
        run(client, config, repository, allow_missing),
    )
    .await
    .map_err(|_| Error::Timeout)?
}
/// Send bounded tool-call requests and append corrective instructions for invalid output.
///
/// # Errors
///
/// Propagates prompt and transport errors; returns [`Error::Generation`] when status,
/// output or aggregate token usage violates the contract.
async fn run(
    client: &Client,
    config: &Config,
    repository: &Repository,
    allow_missing: bool,
) -> Result<Outcome> {
    let mut messages = vec![
        json!({"role": "system", "content": prompt::instructions(allow_missing)}),
        json!({"role": "user", "content": prompt::evidence(repository)?}),
    ];
    let mut consumed = 0;
    for attempt in 0..3 {
        let response = client.post("https://opencode.ai/inference/openai/v1/chat/completions")
            .bearer_auth(&config.zen_key).timeout(Duration::from_secs(120))
            .json(&json!({"model": config.zen_model, "messages": messages, "tools": prompt::tools(), "max_tokens": 2048, "stream": false})).send().await?;
        if !response.status().is_success() {
            return Err(Error::Generation);
        }
        let response: Response =
            serde_json::from_slice(&http::bounded(response, 256 * 1024).await?)?;
        consumed += response
            .usage
            .as_ref()
            .map_or(2048, |usage| usage.completion_tokens);
        if consumed > 6144 {
            return Err(Error::Generation);
        }
        let outcome = resolve(response, repository, allow_missing);
        match outcome {
            Ok(outcome) => return Ok(outcome),
            Err(_) if attempt < 2 => messages.push(json!({"role": "user", "content": "The result violated the output contract. Return exactly one output tool with bounded plain text, 3–5 distinct supported features, 1–3 valid tags, exact eligible link IDs, and total text <=950 characters. Omit duplicate destinations. A missing download outcome is permitted only without verified candidates and without staff approval. Do not invent claims."})),
            Err(_) => break,
        }
    }
    Err(Error::Generation)
}
/// Accept exactly one recognized tool call and validate its outcome.
///
/// Rejects length-truncated responses and permits missing-download results only
/// when no candidate exists and staff have not approved proceeding without one.
///
/// # Errors
///
/// Returns JSON errors for malformed arguments and [`Error::Generation`] for
/// invalid tool selection, cardinality, plain text or resolved draft content.
fn resolve(response: Response, repository: &Repository, allow_missing: bool) -> Result<Outcome> {
    let [choice] = response.choices.as_slice() else {
        return Err(Error::Generation);
    };
    if choice.finish_reason.as_deref() == Some("length") {
        return Err(Error::Generation);
    }
    let [call] = choice.message.tool_calls.as_slice() else {
        return Err(Error::Generation);
    };
    if call.function.name == "return_post_draft" {
        let generated: GeneratedPost = serde_json::from_str(&call.function.arguments)?;
        return generated
            .resolve(repository, allow_missing)
            .map(Outcome::Draft);
    }
    let reason: Reason = serde_json::from_str(&call.function.arguments)?;
    let reason = validate_plain_text(&reason.reason, 280)?;
    match call.function.name.as_str() {
        "not_android_project" => Ok(Outcome::NotAndroid(reason)),
        "insufficient_repository_evidence" => Ok(Outcome::Insufficient(reason)),
        "missing_download_source" if !allow_missing && !repository.has_download() => {
            Ok(Outcome::MissingDownload(reason))
        }
        _ => Err(Error::Generation),
    }
}
