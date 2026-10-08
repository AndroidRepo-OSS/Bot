---
name: androidrepo-publication
description: Change or review Android Repository publication reservations, Telegram delivery recovery, PostgreSQL transitions, or reconciliation. Use when duplicate prevention or durable publication state is involved.
---

# Durable publication

Read `posts/publication.py`, `db/publications.py`, and `db/models.py` together
before changing delivery behavior. The database and Telegram cannot share a
transaction; each transition must account for that gap.

- Commit a `copying` reservation before calling Telegram. All transitions lock
  the repository with the same transaction-level advisory lock before taking
  an operation row lock. Preserve the unique open-operation and channel-receipt
  constraints.
- A live copy lease means in progress. An expired lease means delivery is
  unresolved, never permission for another copy. Use the database's current
  clock after lock waits when deciding lease ownership.
- A receipt must become a Publication and a completed operation atomically.
  Once Telegram returns a receipt, finish storing or compensating it despite
  ordinary update cancellation.
- Persist `compensating` with its receipt before deleting a channel copy. If
  deletion fails or is ambiguous, keep the repository blocked or conservatively
  record the receipt. Only confirmed deletion may release the reservation.
- Definitive Telegram rejection can mark an operation failed. Timeout, network
  failure, server error, or cancellation cannot prove non-delivery.
- Staff reconciliation records a visible receipt or confirms absence. It never
  sends another channel copy and cannot override a live copy lease.
- Preserve the three-calendar-month cooldown, owner checks, provider-stable
  identity, aliases, and monotonic first/last-seen bounds under concurrency.

Reuse database reservation results directly for blocked and in-progress
publication outcomes. `mark_publication_delivery` accepts the typed receiptless
status (`uncertain` or `failed`); it does not establish non-delivery itself.

Prefer typed ORM assignments inside `sessions.begin()` over untyped update
maps. Do not rewrite deployed Alembic revisions; add one only if the schema
needs to change. Log operation IDs, channel receipt IDs, and exception types,
not raw database/Telegram exceptions or private message content.

Run the root verification sequence and compile migrations with Alembic's
`--sql` mode when relevant. Real concurrency/migration verification requires a
disposable PostgreSQL instance; report clearly when only offline checks were
possible. Do not add test suites or contact a live channel without user scope.
