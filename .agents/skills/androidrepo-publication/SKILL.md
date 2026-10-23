---
name: androidrepo-publication
description: Change or review Android Repository Bot's publication reservations, receipt persistence, compensation, cooldown or reconciliation.
---

# Durable publication

Read `src/bot/publication.rs`, `src/db/publications.rs`, SQLite connection policy
in `src/db/mod.rs` and the affected SQL migrations together. Telegram delivery
and database transitions cannot share a transaction; keep their coordination explicit.

## Preserve

- Commit `copying` before the single channel-copy request. Never automatically
  retry a copy. Definitive API rejection may release the reservation; timeout,
  transport failure, invalid response and unknown errors mean unresolved delivery.
- Acquire SQLite's writer lock with `BEGIN IMMEDIATE` before reading state in
  write transactions. Read the database clock after lock waits. Keep unique open
  operations/receipts and the UTC three-calendar-month cooldown, including
  month-end behavior.
- Preserve file-backed SQLite, WAL journaling, `synchronous=FULL`, foreign keys
  and the busy timeout. Use a local persistent filesystem with reliable file
  locks; processes sharing the database must use the same file on the same host.
- A live lease prevents reconciliation; expiration never authorizes another copy.
  Store the receipt, publication and completed operation atomically. Keep the
  publication future owned by the draining dispatcher after delivery.
- Persist `compensating`, its receipt and lease before deletion. Only confirmed
  deletion releases the reservation. Ambiguous or failed deletion retains recovery
  state or a conservatively recorded publication.
- Reconciliation records a visible receipt or confirms absence; it never copies.
  Validate the operation's channel and preserve idempotence and receipt matching.
- Preserve stable repository identity, alias history and monotonic observation
  timestamps. Add SQL revisions instead of editing deployed migrations; keep
  existing SQLx checksums and supported database adoption intact.

## Verify the affected boundary

Use a disposable file-backed SQLite database and synthetic data, never production
fault injection. Use the application's connection policy; in-memory databases
cannot verify restart recovery or the deployed locking and journaling behavior.
Exercise the scenarios affected by the change: fresh migration and reopening the
same file; concurrent reservations through separate connections; live/expired
copy and compensation leases; repeated receipt completion; unique receipts;
month-end cooldown; and interrupted compensation.

For delivery changes, use a local Telegram API stub. Check definitive rejection,
ambiguous response without a second copy, post-copy persistence failure,
confirmed/failed compensation and reconciliation after expiry. Run the root
checks and report which database/stub scenarios ran and which remain unverified.
