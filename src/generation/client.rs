//! Bounded Chat Completions tool-call generation and corrective requests.
//!
//! [`generate`] limits total deadline, requests, response bytes and output tokens.
//! Only one recognized tool call is accepted; free-form output never becomes a post.

use super::{
    Draft, GeneratedPost, Outcome, Reason, Rejection, ValidationResult, prompt, validate_plain_text,
};
use crate::{
    config::Config,
    error::{Error, Result},
    http,
    repositories::Repository,
};
use reqwest::{Client, RequestBuilder, StatusCode};
use serde::Deserialize;
use serde_json::json;
use std::time::{Duration, Instant};

/// Maximum body size for both pending and completed NVIDIA responses.
const RESPONSE_LIMIT: usize = 256 * 1024;

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
    /// Structured outputs; absent or null calls fail validation and trigger correction.
    #[serde(default)]
    tool_calls: Option<Vec<Call>>,
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
/// Uses at most three submissions, each with 2,048 output tokens, and a 6,144-token
/// aggregate budget. Pending submissions are polled without resubmission, within the
/// same deadline. Corrective requests follow invalid output, not arbitrary HTTP
/// failures. `allow_missing` must reflect staff approval, never repository text.
/// The consumer's synchronous `validate` checks the assembled draft on every attempt.
/// This contacts the configured model provider and may consume billed tokens.
///
/// # Errors
///
/// Returns [`Error::Timeout`] on the total deadline, sanitized HTTP/JSON/payload
/// errors on failed reads, categorized HTTP failures, or [`Error::Generation`] for
/// rejected output/budget.
pub async fn generate(
    client: &Client,
    config: &Config,
    repository: &Repository,
    allow_missing: bool,
    validate: impl Fn(&Draft) -> Result<()>,
) -> Result<Outcome> {
    tokio::time::timeout(
        Duration::from_secs(120),
        run(client, config, repository, allow_missing, validate),
    )
    .await
    .map_err(|_| Error::Timeout)?
}
/// Send bounded tool-call requests and append corrective instructions for invalid output.
///
/// # Errors
///
/// Propagates prompt, transport and categorized HTTP errors; returns
/// [`Error::Generation`] when output or aggregate token usage violates the contract.
async fn run(
    client: &Client,
    config: &Config,
    repository: &Repository,
    allow_missing: bool,
    validate: impl Fn(&Draft) -> Result<()>,
) -> Result<Outcome> {
    let mut messages = vec![
        json!({"role": "system", "content": prompt::instructions(allow_missing)}),
        json!({"role": "user", "content": prompt::evidence(repository)?}),
    ];
    let mut consumed = 0_u64;
    for attempt in 0..3 {
        let request = client
            .post("https://integrate.api.nvidia.com/v1/chat/completions")
            .bearer_auth(&config.nvidia_key)
            .header(reqwest::header::ACCEPT, "application/json")
            .timeout(Duration::from_secs(120))
            .json(&json!({
                "model": config.nvidia_model,
                "messages": messages,
                "tools": prompt::tools(),
                "tool_choice": "required",
                "parallel_tool_calls": false,
                // Reserve the bounded completion budget for the structured result.
                "reasoning_effort": "none",
                "max_tokens": 2048,
                "stream": false
            }));
        let response = send(request, attempt + 1, 0).await?;
        let response = complete(client, &config.nvidia_key, response, attempt + 1).await?;
        let response: Response =
            serde_json::from_slice(&http::bounded(response, RESPONSE_LIMIT).await?)?;
        consumed = consumed.saturating_add(
            response
                .usage
                .as_ref()
                .map_or(2048, |usage| usage.completion_tokens),
        );
        if consumed > 6144 {
            return Err(Error::Generation);
        }
        let outcome = resolve(response, repository, allow_missing).and_then(|outcome| {
            if let Outcome::Draft(draft) = &outcome {
                validate(draft).map_err(|_| Rejection::Caption)?;
            }
            Ok(outcome)
        });
        match outcome {
            Ok(outcome) => return Ok(outcome),
            Err(rejection) if attempt < 2 => {
                tracing::debug!(attempt = attempt + 1, category = ?rejection, "generation output rejected");
                messages.push(json!({"role": "user", "content": format!(
                    "The result violated the output contract. {} Return a new complete result grounded only in the supplied evidence and follow the trusted staff download policy. Do not invent claims.",
                    rejection.correction()
                )}));
            }
            Err(_) => break,
        }
    }
    Err(Error::Generation)
}
/// Execute one inference submission or status read without transport retries.
///
/// Logs only numeric request context and sanitized categories, never URLs, IDs or bodies.
///
/// # Errors
///
/// Returns sanitized transport errors or an HTTP category; only 200 and 202 are accepted.
async fn send(request: RequestBuilder, attempt: u32, poll: u32) -> Result<reqwest::Response> {
    let started = Instant::now();
    let result = request.send().await;
    let elapsed_ms = started.elapsed().as_millis() as u64;
    let response = result.map_err(|error| {
        let error = Error::from(error);
        tracing::warn!(attempt, poll, elapsed_ms, category = %error, "NVIDIA transport failed");
        error
    })?;
    let status = response.status();
    tracing::debug!(
        attempt,
        poll,
        elapsed_ms,
        status = status.as_u16(),
        "NVIDIA response received"
    );
    if matches!(status, StatusCode::OK | StatusCode::ACCEPTED) {
        return Ok(response);
    }
    let error = match status.as_u16() {
        401 | 403 => {
            Error::Config("NVIDIA API authentication or access denied; check nvidia_api_key")
        }
        400 | 404 | 422 if poll == 0 => {
            Error::Config("NVIDIA model or generation parameters rejected; check nvidia_model")
        }
        402 => Error::Config("NVIDIA API credits exhausted"),
        429 => Error::RateLimit,
        408 | 504 => Error::Timeout,
        _ => Error::External,
    };
    tracing::warn!(attempt, poll, elapsed_ms, status = status.as_u16(), category = %error, "NVIDIA HTTP request rejected");
    Err(error)
}

/// Retrieve a pending inference from NVIDIA's fixed status origin without resubmitting it.
///
/// Accepts only bounded path-safe request IDs from the initial 202 response. Ignores
/// arbitrary response URLs and later IDs. At most 120 polls, spaced by one second,
/// run inside [`generate`]'s total deadline; all response bodies remain bounded.
///
/// # Errors
///
/// Returns [`Error::Payload`] for missing/invalid IDs or excessive bodies, categorized
/// request errors, or [`Error::Timeout`] when the polling budget is exhausted.
async fn complete(
    client: &Client,
    key: &str,
    mut response: reqwest::Response,
    attempt: u32,
) -> Result<reqwest::Response> {
    if response.status() == StatusCode::OK {
        return Ok(response);
    }
    let id = response
        .headers()
        .get("NVCF-REQID")
        .and_then(|value| value.to_str().ok())
        .filter(|id| {
            !id.is_empty()
                && id.len() <= 128
                && id
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
        })
        .ok_or(Error::Payload)?;
    let url = format!("https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/{id}");
    for poll in 1..=120 {
        http::bounded(response, RESPONSE_LIMIT).await?;
        tokio::time::sleep(Duration::from_secs(1)).await;
        response = send(
            client
                .get(&url)
                .bearer_auth(key)
                .header(reqwest::header::ACCEPT, "application/json")
                .header("NVCF-POLL-SECONDS", "10")
                .timeout(Duration::from_secs(120)),
            attempt,
            poll,
        )
        .await?;
        if response.status() == StatusCode::OK {
            return Ok(response);
        }
    }
    Err(Error::Timeout)
}

/// Accept exactly one recognized tool call and validate its outcome.
///
/// Rejects length-truncated responses and permits missing-download results only
/// when no candidate exists and staff have not approved proceeding without one.
///
/// # Errors
///
/// Returns a safe rejection category for malformed arguments, invalid tool selection,
/// cardinality, plain text or resolved draft content.
fn resolve(
    response: Response,
    repository: &Repository,
    allow_missing: bool,
) -> ValidationResult<Outcome> {
    let [choice] = response.choices.as_slice() else {
        return Err(Rejection::Tool);
    };
    if choice.finish_reason.as_deref() == Some("length") {
        return Err(Rejection::Truncated);
    }
    let [call] = choice.message.tool_calls.as_deref().unwrap_or_default() else {
        return Err(Rejection::Tool);
    };
    if call.function.name == "return_post_draft" {
        let generated: GeneratedPost =
            serde_json::from_str(&call.function.arguments).map_err(|_| Rejection::Schema)?;
        return generated
            .resolve(repository, allow_missing)
            .map(Outcome::Draft);
    }
    let reason: Reason =
        serde_json::from_str(&call.function.arguments).map_err(|_| Rejection::Schema)?;
    let reason = validate_plain_text(&reason.reason, 280)?;
    match call.function.name.as_str() {
        "not_android_project" => Ok(Outcome::NotAndroid(reason)),
        "insufficient_repository_evidence" => Ok(Outcome::Insufficient(reason)),
        "missing_download_source" if !allow_missing && !repository.has_download() => {
            Ok(Outcome::MissingDownload(reason))
        }
        "missing_download_source" => Err(Rejection::Download),
        _ => Err(Rejection::Tool),
    }
}
