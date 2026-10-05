---
name: androidrepo-evidence
description: Change GitHub/GitLab evidence fetching, README link extraction, structured post generation, or NASA image validation in Android Repository bot.
---

# Evidence boundaries

Start with the relevant provider in `repositories/`, normalized models, and
`generation/service.py`. Treat provider responses, repository text, generated
output, and artwork metadata as untrusted values.

- Accept public GitHub/GitLab repository roots only. Validate provider-reported
  visibility before fetching further evidence, even with authenticated tokens.
  Preserve provider-stable IDs across renames and aliases.
- Keep HTTP reads bounded, redirects and origins explicit, and retries limited
  to transient failures. Credentials belong only on their provider's requests.
  Do not log raw response bodies, secret-bearing URLs, or exception chains.
- README link extraction uses CommonMark plus the standard HTML parser without
  executing HTML or fetching linked resources. Preserve the scan/link limits;
  exclude code, hidden markup, and image sources. Validate resolved destinations
  and deduplicate canonical URLs before classification.
- The model selects identifiers from inspected evidence. Application code
  resolves URLs and enforces eligible download sources and optional-link rules.
  Never accept a model-provided destination URL directly.
- Keep dynamic staff approval separate from untrusted repository evidence.
  Preserve prompt bounds, output budgets, request/deadline limits, schema
  validation, and explicit insufficient-evidence/non-Android outcomes.
- Use Pydantic constraints at untrusted boundaries and immutable dataclasses
  for already validated workflow values. Avoid validating the same shape in
  several layers without a distinct invariant.
- NASA downloads stay on the approved HTTPS asset host with bounded bytes,
  decode limits, and an offline fallback. Keep packaged assets and licenses.

Use official library documentation or Context7 for changed APIs. Run the root
verification sequence; do not add tests or paid model evaluations unless
requested. For rendering changes, inspect a local offline banner and verify
that attribution remains legible.
