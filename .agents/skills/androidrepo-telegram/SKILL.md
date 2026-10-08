---
name: androidrepo-telegram
description: Change the Android Repository bot's aiogram commands, callbacks, draft FSM, or polling lifecycle. Use for this repository's Telegram workflows and authorization changes.
---

# Telegram workflows

Read `src/androidrepo_bot/dispatcher.py`, then the relevant module in `posts/`.
Use the installed aiogram API and official documentation or Context7 when an
API is uncertain. Keep application composition in `app.py`.

- Admission runs after aiogram's user-context middleware and before its FSM
  middleware. Only `/start` is public; other work requires the configured
  staff chat, post topic, and an identified user.
- Command routes include public `/start`; presentation, callback filters, and
  message operations live together in `posts/telegram.py`. Use native `Command`,
  `StateFilter`, typed `CallbackData`, handler flags,
  `CallbackAnswerMiddleware`, and dependency injection. Keep extra wrappers
  only when they enforce an application invariant.
- `DraftState` holds typed immutable values in process-local `MemoryStorage`.
  `PostDraftState` is the single source of workflow phase. Preserve per-user
  isolation; restarting the process discards drafts.
- `active_draft` also injects typed FSM access with the verified draft context.
  `active_draft` and `pending_download` bind callbacks to both owner and
  message. A valid callback payload or matching FSM phase alone is insufficient.
- Regeneration keeps the existing draft usable on failure. Store its successful
  replacement before deleting the previous message. Audit delivery and draft
  cleanup are best effort; channel compensation is a durable publication step.
- `DrainingDispatcher` tracks admitted `feed_update` calls, including those
  waiting for FSM isolation, and drains them before `emit_shutdown` closes
  storage. Do not replace this with private aiogram task inspection or detached
  work that can outlive database and HTTP resources.
- The `Polling` protocol describes the public interface used by `app.py` and
  avoids aiogram's dynamic `UNSET` annotation. It is not a second polling loop.

For verification use the root `AGENTS.md` sequence. Do not add test or eval
files unless the user requests them. Use offline inspection or temporary smoke
commands when useful; do not send real Telegram messages during verification
without authorization. Include a rendered example when changing visible copy
or banner layout.
