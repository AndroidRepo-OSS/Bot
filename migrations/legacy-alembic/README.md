# Historical migrations

These are the original deployed Alembic revisions, preserved byte for byte for
audit and recovery. They are not imported, packaged as Python, or executed by
the Rust application. Use the previous Python release to upgrade a database
older than `20260812_0003` before switching to Rust.

SQLx embeds only the numbered `.sql` files directly in `migrations/`.
