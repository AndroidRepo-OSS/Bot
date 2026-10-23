---
name: androidrepo-telegram
description: Change or review Android Repository Bot's teloxide commands, callback admission, draft state, Telegram presentation or polling lifecycle.
---

# Telegram workflows

Start at the affected handler in `src/bot/handlers.rs`; follow state and shutdown
in `mod.rs`, draft preparation in `drafts.rs` or presentation in `ui.rs` as needed.
Inspect the exact Git-pinned teloxide source when changing dispatcher behavior.
Channel delivery and compensation also require `androidrepo-publication`.

## Preserve

- Only `/start` is public. Other actions require the configured staff chat/topic
  and an identified user. Keep command parsing in the typed `BotCommands` filter.
- Commands and callbacks share per-user dispatcher isolation. State mutexes cover
  short map accesses, never external I/O. State owns the workflow phase.
- Validate callback owner, active message and allowed phase together, including
  missing-download approval. A syntactically valid payload grants no authority.
- Keep a usable draft on regeneration failure. Store its replacement before
  removing the previous message. Draft cleanup and audits are best effort;
  channel compensation follows the durable publication protocol.
- Escape Telegram HTML and check final captions in UTF-16 units. Presentation
  receives resolved URLs from evidence validation rather than model-created URLs.
- SIGINT/SIGTERM stop polling and drain admitted work, including queued updates,
  before closing resources. Keep one polling loop and no detached publications.
  Disable dependency logging that exposes raw Telegram errors or private content.

## Verify the affected boundary

Use synthetic updates and a local Telegram API stub for owner/topic/message
checks, wrong-phase confirmation, confirmation/back/cancel, missing-download
approval and regeneration failure. For lifecycle changes, check shutdown with
queued work and an in-flight publication. For visible changes, inspect a caption
or rendered banner with attribution. Run the applicable root checks; report stub
coverage separately from any explicitly requested staging integration.
