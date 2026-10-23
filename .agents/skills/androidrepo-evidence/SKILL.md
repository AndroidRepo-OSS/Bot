---
name: androidrepo-evidence
description: Change or review Android Repository Bot's public repository evidence, README links, generation validation or NASA artwork handling.
---

# Evidence boundaries

Follow the affected path from `src/repositories/` and shared `src/http.rs` to
its consumer in `src/generation/` or `src/media/`. Keep provider parsing separate
from Telegram presentation; generation returns validated destinations.

## Preserve

- Check public visibility before secondary requests, even with authentication.
  Preserve stable provider IDs and observed aliases across repository renames.
- Bound external reads and scope credentials to their provider origin. GitLab's
  latest-release permalink redirects; use the sorted release list while keeping
  redirects disabled.
- Parse README CommonMark and HTML as inert evidence. Exclude code, hidden markup
  and image sources; retain the 50,000-character scan and 20-link extraction bounds.
- Resolve model-selected link IDs through the same inspected evidence snapshot.
  Download must be an eligible release, app store or package source; repository
  and donation links cannot become optional model-selected destinations.
- Keep staff approval separate from untrusted evidence in the prompt. Preserve
  the four generation outcomes, escaped evidence, distinct features/tags,
  request/token/deadline bounds and final caption validation.
- Restrict NASA assets to the approved HTTPS origin, byte and decoder limits.
  Decode/render through the bounded blocking pool; keep offline fallback and
  visible artwork and Android attribution.

## Verify the affected boundary

Use `inspect <public-repository-url> --output /tmp/evidence.json` for read-only
provider inspection and `render-banner --help` for offline rendering options;
run either through `cargo run --release --locked --`. Neither needs model,
Telegram or database credentials.

For parsing changes, probe rejected URL forms and README code/hidden/image links.
For generation validation, use synthetic output to check invented IDs, duplicate
features/tags and oversized or delimiter-bearing evidence. For media changes,
render short, long and Unicode titles and inspect the PNG and attribution.
Run the applicable root checks. Report external checks actually performed and
any offline limitations.
