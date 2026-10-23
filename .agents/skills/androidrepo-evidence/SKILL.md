---
name: androidrepo-evidence
description: Change public GitHub/GitLab evidence, README destination extraction, structured generation or NASA artwork validation in Android Repository Bot.
---

# Evidence boundaries

Read the affected provider in `src/repositories/`, shared `client.rs`/`http.rs`,
and the corresponding consumer in `src/generation/` or `src/media/`.

- Validate public visibility before secondary requests, including authenticated
  requests. Preserve stable provider identity and aliases across renames.
- Keep bounded bodies, per-request credentials and explicit origins. GitLab's
  latest-release permalink redirects; use the sorted release list rather than
  enabling blanket redirects. Never log raw response errors or bodies.
- Parse README CommonMark as inert HTML. Exclude code, hidden markup and image
  sources; preserve the 50,000-character scan and 20 extracted-link bounds.
- Generated destinations are IDs resolved through the same evidence snapshot.
  Download requires an eligible release/store/package source. Repository and
  donation links cannot be optional model selections.
- Staff approval is a system instruction separate from untrusted evidence.
  Preserve four outcomes, text/distinctness constraints, escaped evidence,
  request/token/deadline limits and the final caption check.
- NASA downloads use only the approved asset origin, bounded bytes and decoder
  limits. Run CPU decoding/rendering on the bounded blocking pool. Preserve
  offline fallback and visible attribution.

Use official docs for changed crate/provider APIs and run the root verification.
Use `inspect` for public read-only evidence and `render-banner` for an offline
visual check. Neither needs model or Telegram credentials. Do not add paid
model calls, test suites or evaluation datasets as verification side effects.
