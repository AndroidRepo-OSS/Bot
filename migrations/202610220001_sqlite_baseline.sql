-- Timestamps are RFC 3339 UTC text; tags are JSON arrays.
CREATE TABLE repository_apps (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id <= 2147483647),
    provider TEXT NOT NULL,
    provider_repository_id TEXT NOT NULL,
    current_namespace TEXT NOT NULL,
    current_name TEXT NOT NULL,
    current_url TEXT NOT NULL,
    display_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (provider, provider_repository_id),
    CHECK (julianday(first_seen_at) IS NOT NULL AND julianday(last_seen_at) IS NOT NULL
        AND julianday(first_seen_at) <= julianday(last_seen_at))
) STRICT;

CREATE TABLE repository_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id <= 2147483647),
    repository_app_id INTEGER NOT NULL REFERENCES repository_apps(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    url TEXT NOT NULL,
    observed_at TEXT NOT NULL CHECK (julianday(observed_at) IS NOT NULL),
    UNIQUE (repository_app_id, full_name, url)
) STRICT;

CREATE TABLE post_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id <= 2147483647),
    repository_app_id INTEGER REFERENCES repository_apps(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    namespace TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    requested_by_user_id INTEGER NOT NULL,
    attempted_at TEXT NOT NULL CHECK (julianday(attempted_at) IS NOT NULL),
    status TEXT NOT NULL,
    blocked_until TEXT CHECK (blocked_until IS NULL OR julianday(blocked_until) IS NOT NULL),
    reason TEXT,
    CHECK (status = 'blocked' AND blocked_until IS NOT NULL AND reason IS NOT NULL AND reason = 'cooldown')
) STRICT;
CREATE INDEX ix_post_attempts_repository_attempted_at ON post_attempts(repository_app_id, attempted_at);

CREATE TABLE published_posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id <= 2147483647),
    repository_app_id INTEGER NOT NULL REFERENCES repository_apps(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    tags TEXT NOT NULL CHECK (json_valid(tags) AND json_type(tags) = 'array'),
    created_by_user_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    channel_message_id INTEGER NOT NULL,
    published_at TEXT NOT NULL CHECK (julianday(published_at) IS NOT NULL),
    UNIQUE (channel_id, channel_message_id)
) STRICT;
CREATE INDEX ix_published_posts_repository_published_at ON published_posts(repository_app_id, julianday(published_at));

CREATE TABLE publication_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT CHECK (id <= 2147483647),
    repository_app_id INTEGER NOT NULL REFERENCES repository_apps(id) ON DELETE CASCADE,
    source_chat_id INTEGER NOT NULL,
    source_message_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    actor_user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    tags TEXT NOT NULL CHECK (json_valid(tags) AND json_type(tags) = 'array'),
    status TEXT NOT NULL,
    lease_expires_at TEXT CHECK (lease_expires_at IS NULL OR julianday(lease_expires_at) IS NOT NULL),
    channel_message_id INTEGER,
    published_at TEXT CHECK (published_at IS NULL OR julianday(published_at) IS NOT NULL),
    published_post_id INTEGER UNIQUE REFERENCES published_posts(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL CHECK (julianday(created_at) IS NOT NULL),
    updated_at TEXT NOT NULL CHECK (julianday(updated_at) IS NOT NULL),
    CHECK (
        (status = 'copying' AND lease_expires_at IS NOT NULL AND channel_message_id IS NULL AND published_at IS NULL AND published_post_id IS NULL)
        OR (status = 'compensating' AND channel_message_id IS NOT NULL AND published_at IS NOT NULL AND published_post_id IS NULL)
        OR (status = 'completed' AND lease_expires_at IS NULL AND channel_message_id IS NOT NULL AND published_at IS NOT NULL AND published_post_id IS NOT NULL)
        OR (status IN ('uncertain', 'failed') AND lease_expires_at IS NULL AND channel_message_id IS NULL AND published_at IS NULL AND published_post_id IS NULL)
        OR (status = 'abandoned' AND lease_expires_at IS NULL AND published_post_id IS NULL
            AND ((channel_message_id IS NULL AND published_at IS NULL) OR (channel_message_id IS NOT NULL AND published_at IS NOT NULL)))
    )
) STRICT;
CREATE INDEX ix_publication_operations_status_lease ON publication_operations(status, lease_expires_at);
CREATE UNIQUE INDEX uq_publication_operations_open_repository ON publication_operations(repository_app_id)
    WHERE status IN ('copying', 'compensating', 'uncertain');
