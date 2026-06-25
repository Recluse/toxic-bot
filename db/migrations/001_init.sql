-- 001_init.sql — Full initial schema.
-- Apply once: psql $DATABASE_URL -f db/migrations/001_init.sql

-- -------------------------------------------------------------------------
-- chat_settings
-- One row per Telegram chat (group or private).
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id            BIGINT      PRIMARY KEY,
    lang               VARCHAR(5)  NOT NULL DEFAULT 'en',
    toxicity_level     SMALLINT    NOT NULL DEFAULT 3
                           CHECK (toxicity_level BETWEEN 1 AND 5),
    freq_min           SMALLINT    NOT NULL DEFAULT 5
                           CHECK (freq_min >= 1),
    freq_max           SMALLINT    NOT NULL DEFAULT 15
                           CHECK (freq_max >= freq_min),
    reply_cooldown_sec SMALLINT    NOT NULL DEFAULT 60
                           CHECK (reply_cooldown_sec >= 0),
    reply_chain_depth  SMALLINT    NOT NULL DEFAULT 5
                           CHECK (reply_chain_depth BETWEEN 1 AND 20),
    min_words          SMALLINT    NOT NULL DEFAULT 5
                           CHECK (min_words >= 1),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -------------------------------------------------------------------------
-- message_history
-- Individual conversation turns stored for LLM context.
-- role: 'user' | 'assistant'
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS message_history (
    id         BIGSERIAL   PRIMARY KEY,
    chat_id    BIGINT      NOT NULL,
    user_id    BIGINT      NOT NULL,
    role       VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT        NOT NULL,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index supports the "last N messages for chat" query pattern
CREATE INDEX IF NOT EXISTS idx_history_chat_ts
    ON message_history (chat_id, ts DESC);

-- -------------------------------------------------------------------------
-- user_profiles
-- One row per (chat, user).
-- summary: LLM-generated running psychological/behavioural profile,
--          updated asynchronously after each user message.
-- -------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
    chat_id    BIGINT       NOT NULL,
    user_id    BIGINT       NOT NULL,
    username   VARCHAR(128),
    summary    TEXT         NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (chat_id, user_id)
);
