---
name: androidrepo-telegram
description: Change Android Repository Bot's teloxide commands, callbacks, draft state, Telegram presentation or polling lifecycle.
---

# Telegram workflows

Start with `src/bot/mod.rs`, then `handlers.rs`, `drafts.rs` or `ui.rs` as needed.
Consult the exact Git-pinned teloxide source for dispatch and shutdown behavior.

- Only `/start` is public. Other actions require staff chat, post topic and an
  identified user. Command parsing is teloxide's typed `BotCommands` filter.
- Dispatcher distribution is by user. Commands and callbacks must use the same
  isolation key; state mutexes cover short map accesses, never external I/O.
- State owns the phase. Check callback owner, active message and allowed action
  together, including missing-download approval. A valid payload alone grants
  no authority.
- Keep the current draft on regeneration failure. Store a usable replacement
  before removing the previous message. Audit and draft cleanup are best effort;
  channel compensation follows the durable protocol in `publication.rs`.
- Escape HTML and count final captions in UTF-16 units. Keep generated URLs out
  of presentation logic: UI receives already resolved destinations.
- SIGINT/SIGTERM stop polling and drain workers, including queued updates, before
  closing resources. Do not add detached publication tasks or a second polling
  loop. Disable raw dependency error logging.

Use root checks and temporary synthetic updates/local API stubs for manual
verification. Do not send real Telegram messages incidentally. Include an
inspected banner or caption example for visible changes.
