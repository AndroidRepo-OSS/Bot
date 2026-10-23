-- Adopt the deployed Alembic head without rewriting historical migrations.
-- Fresh databases receive the same schema. Older/unknown schemas must first be
-- upgraded with the previous release, never guessed or stamped over.
DO $migration$
BEGIN
    IF to_regclass('repository_apps') IS NOT NULL THEN
        IF to_regclass('alembic_version') IS NULL THEN
            RAISE EXCEPTION 'Existing database has no recognized migration history';
        END IF;
        IF (SELECT count(*) FROM alembic_version) <> 1
           OR NOT EXISTS (SELECT 1 FROM alembic_version WHERE version_num = '20260812_0003') THEN
            RAISE EXCEPTION 'Upgrade the Python database to 20260812_0003 first';
        END IF;
        IF to_regclass('publication_operations') IS NULL
           OR to_regclass('uq_publication_operations_open_repository') IS NULL THEN
            RAISE EXCEPTION 'Publication schema is incomplete';
        END IF;
    ELSE
        CREATE TABLE alembic_version (
            version_num VARCHAR(32) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        );

        -- Running upgrade  -> 20260625_0001

        CREATE TABLE repository_apps (
            id SERIAL NOT NULL,
            provider VARCHAR(32) NOT NULL,
            provider_repository_id VARCHAR(128) NOT NULL,
            current_namespace VARCHAR(512) NOT NULL,
            current_name VARCHAR(255) NOT NULL,
            current_url VARCHAR(2048) NOT NULL,
            display_name VARCHAR(255) NOT NULL,
            first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
            last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_repository_apps PRIMARY KEY (id),
            CONSTRAINT uq_repository_apps_provider_id UNIQUE (provider, provider_repository_id)
        );

        CREATE TABLE repository_aliases (
            id SERIAL NOT NULL,
            repository_app_id INTEGER NOT NULL,
            provider VARCHAR(32) NOT NULL,
            namespace VARCHAR(512) NOT NULL,
            name VARCHAR(255) NOT NULL,
            full_name VARCHAR(768) NOT NULL,
            url VARCHAR(2048) NOT NULL,
            observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_repository_aliases PRIMARY KEY (id),
            CONSTRAINT fk_repository_aliases_repository_app_id_repository_apps FOREIGN KEY(repository_app_id) REFERENCES repository_apps (id) ON DELETE CASCADE,
            CONSTRAINT uq_repository_aliases_provider_full_name UNIQUE (provider, full_name),
            CONSTRAINT uq_repository_aliases_provider_url UNIQUE (provider, url)
        );

        CREATE TABLE post_attempts (
            id SERIAL NOT NULL,
            repository_app_id INTEGER,
            provider VARCHAR(32) NOT NULL,
            namespace VARCHAR(512) NOT NULL,
            name VARCHAR(255) NOT NULL,
            url VARCHAR(2048) NOT NULL,
            requested_by_user_id BIGINT NOT NULL,
            attempted_at TIMESTAMP WITH TIME ZONE NOT NULL,
            status VARCHAR(32) NOT NULL,
            blocked_until TIMESTAMP WITH TIME ZONE,
            reason VARCHAR(255),
            CONSTRAINT pk_post_attempts PRIMARY KEY (id),
            CONSTRAINT fk_post_attempts_repository_app_id_repository_apps FOREIGN KEY(repository_app_id) REFERENCES repository_apps (id) ON DELETE SET NULL
        );

        CREATE INDEX ix_post_attempts_repository_attempted_at ON post_attempts (repository_app_id, attempted_at);

        CREATE TABLE published_posts (
            id SERIAL NOT NULL,
            repository_app_id INTEGER NOT NULL,
            title VARCHAR(255) NOT NULL,
            tags VARCHAR(64)[] NOT NULL,
            created_by_user_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            channel_message_id BIGINT NOT NULL,
            published_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_published_posts PRIMARY KEY (id),
            CONSTRAINT fk_published_posts_repository_app_id_repository_apps FOREIGN KEY(repository_app_id) REFERENCES repository_apps (id) ON DELETE CASCADE
        );

        CREATE INDEX ix_published_posts_channel_message ON published_posts (channel_id, channel_message_id);

        CREATE INDEX ix_published_posts_repository_published_at ON published_posts (repository_app_id, published_at);

        INSERT INTO alembic_version (version_num) VALUES ('20260625_0001');

        -- Running upgrade 20260625_0001 -> 20260711_0002

        ALTER TABLE repository_aliases DROP CONSTRAINT uq_repository_aliases_provider_full_name;

        ALTER TABLE repository_aliases DROP CONSTRAINT uq_repository_aliases_provider_url;

        ALTER TABLE repository_aliases ADD CONSTRAINT uq_repository_aliases_repository_value UNIQUE (repository_app_id, full_name, url);

        ALTER TABLE repository_aliases DROP COLUMN provider;

        ALTER TABLE repository_apps ADD CONSTRAINT ck_repository_apps_seen_order CHECK (first_seen_at <= last_seen_at);

        ALTER TABLE post_attempts ADD CONSTRAINT ck_post_attempts_blocked_shape CHECK (status = 'blocked' AND blocked_until IS NOT NULL AND reason IS NOT NULL AND reason = 'cooldown');

        DELETE FROM published_posts AS duplicate
                    USING published_posts AS original
                    WHERE duplicate.channel_id = original.channel_id
                      AND duplicate.channel_message_id = original.channel_message_id
                      AND duplicate.id > original.id;

        DROP INDEX ix_published_posts_channel_message;

        ALTER TABLE published_posts ADD CONSTRAINT uq_published_posts_channel_message UNIQUE (channel_id, channel_message_id);

        UPDATE alembic_version SET version_num='20260711_0002' WHERE alembic_version.version_num = '20260625_0001';

        -- Running upgrade 20260711_0002 -> 20260812_0003

        CREATE TABLE publication_operations (
            id SERIAL NOT NULL,
            repository_app_id INTEGER NOT NULL,
            source_chat_id BIGINT NOT NULL,
            source_message_id BIGINT NOT NULL,
            channel_id BIGINT NOT NULL,
            actor_user_id BIGINT NOT NULL,
            title VARCHAR(255) NOT NULL,
            tags VARCHAR(64)[] NOT NULL,
            status VARCHAR(32) NOT NULL,
            lease_expires_at TIMESTAMP WITH TIME ZONE,
            channel_message_id BIGINT,
            published_at TIMESTAMP WITH TIME ZONE,
            published_post_id INTEGER,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
            CONSTRAINT pk_publication_operations PRIMARY KEY (id),
            CONSTRAINT ck_publication_operations_state_shape CHECK ((status = 'copying' AND lease_expires_at IS NOT NULL AND channel_message_id IS NULL AND published_at IS NULL AND published_post_id IS NULL) OR (status = 'compensating' AND lease_expires_at IS NULL AND channel_message_id IS NOT NULL AND published_at IS NOT NULL AND published_post_id IS NULL) OR (status = 'completed' AND lease_expires_at IS NULL AND channel_message_id IS NOT NULL AND published_at IS NOT NULL AND published_post_id IS NOT NULL) OR (status IN ('uncertain', 'failed') AND lease_expires_at IS NULL AND channel_message_id IS NULL AND published_at IS NULL AND published_post_id IS NULL) OR (status = 'abandoned' AND lease_expires_at IS NULL AND published_post_id IS NULL AND ((channel_message_id IS NULL AND published_at IS NULL) OR (channel_message_id IS NOT NULL AND published_at IS NOT NULL)))),
            CONSTRAINT fk_publication_operations_published_post_id_published_posts FOREIGN KEY(published_post_id) REFERENCES published_posts (id) ON DELETE RESTRICT,
            CONSTRAINT fk_publication_operations_repository_app_id_repository_apps FOREIGN KEY(repository_app_id) REFERENCES repository_apps (id) ON DELETE CASCADE,
            CONSTRAINT uq_publication_operations_published_post_id UNIQUE (published_post_id)
        );

        CREATE INDEX ix_publication_operations_status_lease ON publication_operations (status, lease_expires_at);

        CREATE UNIQUE INDEX uq_publication_operations_open_repository ON publication_operations (repository_app_id) WHERE status IN ('copying', 'compensating', 'uncertain');

        UPDATE alembic_version SET version_num='20260812_0003' WHERE alembic_version.version_num = '20260711_0002';
    END IF;
END
$migration$;
