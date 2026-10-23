//! Telegram HTML captions, callback keyboards and message helpers.
//!
//! [`caption`] escapes validated text and checks the visible UTF-16 budget. Keyboards
//! encode typed intent only; handlers enforce authority. Staff cleanup is best effort
//! and must never substitute for durable channel compensation.

use crate::{
    error::{Error, Result},
    generation::Draft,
};
use teloxide::{
    prelude::*,
    types::{
        InlineKeyboardButton as Button, InlineKeyboardMarkup, LinkPreviewOptions, MessageId,
        ParseMode, ThreadId,
    },
};

/// Escape ampersands, angle brackets and double quotes for Telegram HTML.
pub fn escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
/// Format a validated draft as escaped Telegram HTML.
///
/// Counts the fully assembled visible text in UTF-16 code units against the
/// 1,024-unit photo-caption limit. Tags must already satisfy generation validation;
/// this function adds their hashtag markers without revalidating them.
///
/// # Errors
///
/// Returns [`Error::Invalid`] if the visible caption exceeds 1,024 UTF-16 units.
pub fn caption(draft: &Draft) -> Result<String> {
    let mut visible = format!("{}\n\n{}\n\n✨ Key Features:\n", draft.title, draft.summary);
    let mut html = format!(
        "<b>{}</b>\n\n<i>{}</i>\n\n✨ <b>Key Features:</b>\n",
        escape(&draft.title),
        escape(&draft.summary)
    );
    for feature in &draft.features {
        visible.push_str(&format!("• {feature}\n"));
        html.push_str(&format!("• {}\n", escape(feature)));
    }
    visible.push_str("\n🔗 Links:\n");
    html.push_str("\n🔗 <b>Links:</b>\n");
    for link in &draft.links {
        visible.push_str(&format!("• {}\n", link.label));
        html.push_str(&format!(
            "• <a href=\"{}\">{}</a>\n",
            escape(link.url.as_str()),
            escape(&link.label)
        ));
    }
    let tags = draft
        .tags
        .iter()
        .map(|t| format!("#{t}"))
        .collect::<Vec<_>>()
        .join(" ");
    visible.push_str(&format!("\n🏷️ {tags}"));
    html.push_str(&format!("\n🏷️ {tags}"));
    if visible.encode_utf16().count() > 1024 {
        return Err(Error::Invalid(
            "The generated caption exceeds Telegram's limit.",
        ));
    }
    Ok(html)
}
/// Recognized callback intent; authorization and phase checks live in [`super::handlers`].
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Action {
    /// Enter publication confirmation from review phase.
    Publish,
    /// Request the single channel copy from confirmation phase.
    Confirm,
    /// Return from confirmation to review.
    Back,
    /// Request replacement content while retaining the current usable draft.
    Regenerate,
    /// Deactivate and remove the active draft.
    Cancel,
    /// Explicitly approve generation when no download evidence exists.
    WithoutDownload,
    /// Decline the missing-download prompt and deactivate it.
    CancelDownload,
}
impl Action {
    /// Return the exact callback payload used by the inline keyboard.
    pub fn data(self) -> &'static str {
        match self {
            Self::Publish => "post:publish",
            Self::Confirm => "post:confirm_publish",
            Self::Back => "post:back",
            Self::Regenerate => "post:regenerate",
            Self::Cancel => "post:cancel",
            Self::WithoutDownload => "download_confirmation:generate",
            Self::CancelDownload => "download_confirmation:cancel",
        }
    }
    /// Recognize an exact callback payload without granting workflow permission.
    ///
    /// Unknown payloads return `None`; handlers must still verify owner, message and phase.
    pub fn parse(value: &str) -> Option<Self> {
        [
            Self::Publish,
            Self::Confirm,
            Self::Back,
            Self::Regenerate,
            Self::Cancel,
            Self::WithoutDownload,
            Self::CancelDownload,
        ]
        .into_iter()
        .find(|a| a.data() == value)
    }
}
/// Build a callback button with the exact payload for a typed action.
fn button(label: &str, action: Action) -> Button {
    Button::callback(label, action.data())
}
/// Build channel-safe controls containing only an optional resolved Download URL.
pub fn published(draft: &Draft) -> InlineKeyboardMarkup {
    InlineKeyboardMarkup::new(
        draft
            .download_url
            .iter()
            .map(|url| vec![Button::url("📥 Download", url.clone())]),
    )
}
/// Append review or confirmation controls to the optional Download button.
///
/// `confirming` selects Publish now/Back instead of Publish/Regenerate/Cancel.
pub fn draft_keyboard(draft: &Draft, confirming: bool) -> InlineKeyboardMarkup {
    let mut keyboard = published(draft).inline_keyboard;
    if confirming {
        keyboard.push(vec![button("✅ Publish now", Action::Confirm)]);
        keyboard.push(vec![button("↩️ Back", Action::Back)]);
    } else {
        keyboard.push(vec![button("🚀 Publish", Action::Publish)]);
        keyboard.push(vec![
            button("🔄 Regenerate", Action::Regenerate),
            button("✖️ Cancel", Action::Cancel),
        ]);
    }
    InlineKeyboardMarkup::new(keyboard)
}
/// Build the explicit proceed-without-download and cancel approval controls.
pub fn missing_download() -> InlineKeyboardMarkup {
    InlineKeyboardMarkup::new([
        [button("Generate without download", Action::WithoutDownload)],
        [button("Cancel", Action::CancelDownload)],
    ])
}
/// Send plain text in the source chat/topic with link previews disabled.
///
/// This does not set HTML parse mode; use escaped HTML only in dedicated renderers.
///
/// # Errors
///
/// Returns a sanitized Telegram error if delivery fails.
pub async fn say(bot: &Bot, source: &Message, text: impl Into<String>) -> Result<Message> {
    let mut request =
        bot.send_message(source.chat.id, text)
            .link_preview_options(LinkPreviewOptions {
                is_disabled: true,
                url: None,
                prefer_small_media: false,
                prefer_large_media: false,
                show_above_text: false,
            });
    if let Some(thread) = source.thread_id {
        request = request.message_thread_id(thread);
    }
    Ok(request.await?)
}
/// Send a best-effort audit to the configured staff topic.
///
/// The caller must supply safe text. Delivery failure emits a fixed warning and
/// is not returned to the publication workflow.
pub async fn audit(bot: &Bot, chat: i64, topic: i32, text: impl Into<String>) {
    if bot
        .send_message(ChatId(chat), text)
        .message_thread_id(ThreadId(MessageId(topic)))
        .await
        .is_err()
    {
        tracing::warn!("Staff audit delivery failed");
    }
}
/// Clear stale workflow buttons best effort after state has been deactivated.
pub async fn clear_controls(bot: &Bot, source: &Message, id: MessageId) {
    if bot
        .edit_message_reply_markup(source.chat.id, id)
        .reply_markup(InlineKeyboardMarkup::default())
        .await
        .is_err()
    {
        tracing::warn!("Could not deactivate old controls");
    }
}
/// Delete a staff draft/notice best effort; never use for channel compensation.
///
/// Durable channel deletion belongs to [`super::publication`].
pub async fn delete(bot: &Bot, chat: ChatId, message: MessageId) {
    if bot.delete_message(chat, message).await.is_err() {
        tracing::warn!("Draft cleanup failed");
    }
}
/// Send the public introduction and project/community links in the source topic.
///
/// # Errors
///
/// Returns a sanitized Telegram error on delivery failure or [`Error::Payload`]
/// if a bundled destination cannot be parsed.
pub async fn start(bot: &Bot, source: &Message) -> Result<()> {
    let mut buttons = Vec::new();
    for (label, url) in [
        ("💻 Source code", "https://github.com/AndroidRepo-OSS/Bot"),
        ("📢 Channel", "https://t.me/AndroidRepo"),
        ("💬 Community", "https://t.me/AndroidRepo_chat"),
    ] {
        buttons.push(vec![Button::url(
            label,
            url.parse().map_err(|_| Error::Payload)?,
        )]);
    }
    let mut request = bot.send_message(source.chat.id, "🤖 <b>Android Repository Bot</b>\n\nI turn public GitHub and GitLab projects into channel posts with verified links and illustrated banners. Staff review every draft before publication.\n\nDiscover open-source Android projects in our channel and join the community discussion.")
        .parse_mode(ParseMode::Html).reply_markup(InlineKeyboardMarkup::new(buttons));
    if let Some(thread) = source.thread_id {
        request = request.message_thread_id(thread);
    }
    request.await?;
    Ok(())
}
