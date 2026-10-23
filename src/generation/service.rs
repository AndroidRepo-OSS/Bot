use super::{GeneratedPost, Outcome, Reason, plain, prompt};
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

#[derive(Deserialize)]
struct Response {
    choices: Vec<Choice>,
    usage: Option<Usage>,
}
#[derive(Deserialize)]
struct Usage {
    completion_tokens: u64,
}
#[derive(Deserialize)]
struct Choice {
    message: Message,
    finish_reason: Option<String>,
}
#[derive(Deserialize)]
struct Message {
    #[serde(default)]
    tool_calls: Vec<Call>,
}
#[derive(Deserialize)]
struct Call {
    function: Function,
}
#[derive(Deserialize)]
struct Function {
    name: String,
    arguments: String,
}

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
    let reason = plain(&reason.reason, 280)?;
    match call.function.name.as_str() {
        "not_android_project" => Ok(Outcome::NotAndroid(reason)),
        "insufficient_repository_evidence" => Ok(Outcome::Insufficient(reason)),
        "missing_download_source" if !allow_missing && !repository.has_download() => {
            Ok(Outcome::MissingDownload(reason))
        }
        _ => Err(Error::Generation),
    }
}
