# Android Repository Bot

A Rust Telegram bot for staff-reviewed posts about public Android projects on
GitHub and GitLab. It gathers repository evidence, generates an English caption
and a 1920 × 1080 banner, and publishes to a channel after explicit staff approval.

The bot uses NVIDIA for generation and SQLite for publication history and
recovery. Drafts stay in memory; publication records survive restarts.

## Getting started

Install [Rust through rustup](https://www.rust-lang.org/tools/install), a C/C++
compiler, CMake and pkg-config. The toolchain is pinned in
[`rust-toolchain.toml`](rust-toolchain.toml).

You will need a Telegram bot with permission to publish in the target channel,
a staff supergroup with workflow and audit topics, and an NVIDIA API credential.

```bash
cargo build --release --locked
cp config.example.toml config.toml
chmod 600 config.toml
```

Fill in `config.toml`, then validate the settings, apply migrations and start:

```bash
./target/release/androidrepo-bot check-config
./target/release/androidrepo-bot migrate
./target/release/androidrepo-bot run
```

`check-config` validates settings without contacting services. `migrate` requires
only `database_url` and must run before startup. Omitting the subcommand starts
the bot. Use `--config /path/to/config.toml` to select another configuration file.

## Configuration

Settings come only from TOML; environment variables and `.env` are not loaded.
See [`config.example.toml`](config.example.toml) for an annotated example.

| Key | Required to run | Default | Purpose |
| --- | --- | --- | --- |
| `bot_token` | yes | — | Telegram bot credential |
| `staff_chat_id` | yes | — | Staff supergroup ID |
| `post_topic_id` | yes | — | Staff workflow topic ID |
| `log_topic_id` | yes | — | Operational audit topic ID |
| `channel_id` | yes | — | Publication channel ID |
| `nvidia_api_key` | yes | — | NVIDIA API Catalog credential |
| `database_url` | yes | — | Persistent SQLite URL, e.g. `sqlite://androidrepo.db` |
| `log_level` | no | `INFO` | `CRITICAL`, `ERROR`, `WARNING`/`WARN`, `INFO` or `DEBUG` |
| `nvidia_model` | no | `nvidia/nemotron-3.5-super-vl-120b-a12b` | Generation model |
| `github_token` | no | — | GitHub API token |
| `gitlab_token` | no | — | GitLab API token |

Model overrides must support NVIDIA Chat Completions, tool calling and
`reasoning_effort="none"`. Provider tokens are optional; only public repositories
are accepted, including when authenticated.

IDs are TOML integers. Unknown keys and invalid values are rejected. Never commit
credentials: the default `config.toml` is ignored by Git; keep custom configuration
files outside the repository.

Use a writable, persistent SQLite file on a local filesystem. Its parent directory
must exist; `migrate` creates the file if needed. Relative paths resolve from the
working directory, even with a custom configuration path. Prefer an absolute URL
such as `sqlite:///var/lib/androidrepo/androidrepo.db` in deployments. In-memory
databases, URL query options and network filesystems are unsupported.

## Staff workflow

1. Send `/post https://github.com/owner/repository` or a GitLab repository-root URL
   in the configured staff topic.
2. Review the generated caption, links and banner. Use **Regenerate** to request
   another draft; a failure preserves the previous usable draft.
3. Select **Publish**, then **Publish now** to confirm. **Back** returns to review;
   **Cancel** or `/cancel` discards the draft.

Only `/start` is public. Other commands require the configured staff chat and
workflow topic; draft controls are bound to their owner and active message.
Missing download evidence requires staff approval before generating a post
without a Download button. Links must come from inspected repository evidence.

A published project has a cooldown of three calendar months in UTC. Restarting
clears drafts but preserves publication history and unresolved operations.

### Recovering an uncertain publication

The bot reserves publication before sending and never automatically retries a
channel copy. An ambiguous delivery or expired reservation blocks further
publication until staff reconcile it.

Inspect the channel, then resolve the operation using its ID from the recovery
notice:

```text
/reconcile <operation-id> absent
/reconcile <operation-id> <channel-message-id> <ISO-8601-publication-time>
```

Use `absent` only after confirming no post exists. Otherwise, supply the visible
message ID and its actual publication time, for example `2026-10-22T18:00:00-03:00`.
Reconciliation records the outcome without sending another post.

Stop the bot gracefully with SIGINT/SIGTERM and allow in-flight work to finish.
Before a file backup, stop the bot and preserve the database with any remaining
`-wal`/`-shm` files. For live backups, use SQLite's backup API.

## Inspection and offline rendering

Inspect public repository evidence without AI or Telegram calls:

```bash
./target/release/androidrepo-bot inspect https://github.com/AntennaPod/AntennaPod \
  --output /tmp/evidence.json
```

Inspection uses optional provider tokens when configured; no configuration file
is required. Render a banner with bundled artwork without configuration,
credentials or network access:

```bash
./target/release/androidrepo-bot render-banner --title AntennaPod \
  --repository AntennaPod/AntennaPod --stack 'Java · GPL-3.0 · Podcast' \
  --output /tmp/banner.png
```

## Development

One binary owns the shared HTTP and SQLite pools, bounded rendering and Telegram
dispatcher. The main module boundaries are:

| Path | Responsibility |
| --- | --- |
| `src/main.rs`, `src/config.rs` | CLI, settings and resource composition |
| `src/bot/` | Telegram commands, drafts, review UI and publication coordination |
| `src/repositories/` | Public repository evidence and verified links |
| `src/generation/` | Caption generation and output validation |
| `src/media/` | Artwork and attributed banner rendering |
| `src/db/`, `migrations/` | Publication history, recovery and embedded SQL migrations |

Generate the internal reference with `cargo doc --locked --no-deps --open`.
See [AGENTS.md](AGENTS.md) for project constraints and domain verification guidance.
Add migrations for schema changes; never edit an applied revision.

Install the validated [prek](https://prek.j178.dev/) release and enable Git hooks:

```bash
uv tool install prek==0.5.7
prek install
```

Before completing a code or dependency change, run:

```bash
cargo metadata --locked --format-version 1 --no-deps > /dev/null
cargo fmt --all -- --check
cargo clippy --locked --all-targets -- -D warnings
cargo build --release --locked
cargo doc --locked --no-deps
prek run --all-files
```

For documentation-only changes, run `prek run --all-files`. Hook configuration is
in [`prek.toml`](prek.toml); validate it with `prek validate-config prek.toml` after
changes. There is no Rust test suite; verification uses the manual scenarios in
[the project skills](.agents/skills/).

## License

AGPL-3.0-or-later. Bundled assets have their own licenses and attribution
requirements; see the [asset inventory](src/media/assets/README.md). Banners retain
Android and artwork credits. Assets and SQL migrations are embedded in the binary.
