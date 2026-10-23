//! Telegram presentation: escaped HTML and UTF-16 caption accounting.
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

pub fn escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
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
#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Action {
    Publish,
    Confirm,
    Back,
    Regenerate,
    Cancel,
    WithoutDownload,
    CancelDownload,
}
impl Action {
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
fn button(label: &str, action: Action) -> Button {
    Button::callback(label, action.data())
}
pub fn published(draft: &Draft) -> InlineKeyboardMarkup {
    InlineKeyboardMarkup::new(
        draft
            .download_url
            .iter()
            .map(|url| vec![Button::url("📥 Download", url.clone())]),
    )
}
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
pub fn missing_download() -> InlineKeyboardMarkup {
    InlineKeyboardMarkup::new([
        [button("Generate without download", Action::WithoutDownload)],
        [button("Cancel", Action::CancelDownload)],
    ])
}
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
pub async fn delete(bot: &Bot, chat: ChatId, message: MessageId) {
    if bot.delete_message(chat, message).await.is_err() {
        tracing::warn!("Draft cleanup failed");
    }
}
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
