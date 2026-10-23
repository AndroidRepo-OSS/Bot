---
name: androidrepo-publication
description: Change or review Android Repository Bot's publication reservations, Telegram compensation, PostgreSQL transitions, cooldown or reconciliation.
---

# Durable publication

Read `src/bot/publication.rs`, `src/db/publications.rs` and the current SQL
migrations together. The database and Telegram cannot share a transaction.

- Commit `copying` before the only copy request. Every transition takes the same
  repository advisory lock before the operation row lock. Keep the unique open
  operation and channel receipt constraints.
- Read `clock_timestamp()` after lock waits. A live copy lease means in progress;
  expiry means unresolved delivery, never permission for another copy.
- Store the receipt, Publication and completed operation atomically. Keep the
  future owned by the draining dispatcher; never cancel it after delivery.
- Persist `compensating`, its receipt and lease before deletion. Live compensation
  also blocks staff reconciliation. Only confirmed deletion releases the
  reservation. Failed deletion retains recovery or a conservative Publication.
- Known definitive API rejection can release an operation. Timeout, transport,
  invalid response and unknown API errors cannot establish non-delivery.
- Reconciliation records a visible receipt or confirms absence; it never copies.
  Validate the operation's channel and preserve idempotence/receipt matching.
- Keep UTC three-calendar-month cooldown, stable provider IDs, alias history and
  monotonic observation timestamps. Do not replace them with process locks or
  fixed-day arithmetic.

Use a disposable PostgreSQL for reservations, concurrent contenders, live/expired
leases and failure injection. Local API stubs can exercise delivery without a
real channel. Add SQL revisions rather than editing deployed migrations; verify
fresh and supported legacy adoption. See `docs/validation.md` and root checks.
