-- ============================================================
-- CloudRAG-Hub Database Schema (PostgreSQL)
-- 角色：成员 4 (DBA) → 交接给：成员 3 (后端核心) & 成员 5 (大数据)
-- 最后更新：2026-06-09
-- ============================================================

-- 清理（仅开发环境）
-- DROP TABLE IF EXISTS operation_logs CASCADE;
-- DROP TABLE IF EXISTS messages CASCADE;
-- DROP TABLE IF EXISTS conversations CASCADE;
-- DROP TABLE IF EXISTS file_metadata CASCADE;
-- DROP TABLE IF EXISTS users CASCADE;

-- ============================================================
-- 扩展
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- 1. 用户表
-- ============================================================
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(32)  NOT NULL UNIQUE,
    email           VARCHAR(255) NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    avatar_url      VARCHAR(512),
    role            VARCHAR(16)  NOT NULL DEFAULT 'user'
                    CHECK (role IN ('user', 'admin')),
    quota_used_bytes   BIGINT NOT NULL DEFAULT 0,
    quota_total_bytes  BIGINT NOT NULL DEFAULT 1073741824,  -- 1GB
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);

CREATE INDEX idx_users_username ON users (username);
CREATE INDEX idx_users_email ON users (email);
CREATE INDEX idx_users_role ON users (role);

-- ============================================================
-- 2. 文件元数据表
-- ============================================================
CREATE TABLE file_metadata (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    original_name   VARCHAR(500) NOT NULL,
    stored_name     VARCHAR(255) NOT NULL,
    storage_path    VARCHAR(1024) NOT NULL,
    mime_type       VARCHAR(127) NOT NULL,
    size_bytes      BIGINT NOT NULL,
    tags            TEXT[] DEFAULT '{}',
    description     VARCHAR(500),
    folder          VARCHAR(255) NOT NULL DEFAULT '',
    processing_status VARCHAR(16) NOT NULL DEFAULT 'pending'
                    CHECK (processing_status IN ('pending', 'processing', 'ready', 'failed')),
    duplicate_of    UUID REFERENCES file_metadata(id) ON DELETE SET NULL,
    dify_document_id VARCHAR(64),
    dify_sync_status VARCHAR(32) NOT NULL DEFAULT 'local',
    uploaded_by     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_files_uploaded_by ON file_metadata (uploaded_by);
CREATE INDEX idx_files_status ON file_metadata (processing_status);
CREATE INDEX idx_files_created_at ON file_metadata (created_at DESC);
CREATE INDEX idx_files_mime_type ON file_metadata (mime_type);
CREATE INDEX idx_files_tags ON file_metadata USING GIN (tags);
CREATE INDEX idx_files_folder ON file_metadata (folder);
CREATE INDEX idx_files_duplicate_of ON file_metadata (duplicate_of);
CREATE INDEX idx_files_dify_document_id ON file_metadata (dify_document_id);
CREATE INDEX idx_files_dify_sync_status ON file_metadata (dify_sync_status);

-- File-level vectors used by the BFF duplicate-distance pre-check.
CREATE TABLE file_vectors (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    file_id         UUID NOT NULL REFERENCES file_metadata(id) ON DELETE CASCADE,
    embedding       JSONB NOT NULL,
    model           VARCHAR(64) NOT NULL DEFAULT 'qwen3-embedding:4b',
    dimensions      INTEGER NOT NULL DEFAULT 2560,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

CREATE INDEX idx_file_vectors_file_id ON file_vectors (file_id);
CREATE INDEX idx_file_vectors_model ON file_vectors (model);

-- Mobile channel session context used by the Clawbot/WeChat adapter.
CREATE TABLE mobile_session_context (
    external_user_id VARCHAR(128) PRIMARY KEY,
    mode            VARCHAR(32) NOT NULL DEFAULT 'idle',
    target_file_id  UUID REFERENCES file_metadata(id) ON DELETE SET NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mobile_session_mode ON mobile_session_context (mode);

-- 软删除过滤辅助
CREATE OR REPLACE VIEW file_metadata_active AS
    SELECT * FROM file_metadata WHERE deleted_at IS NULL;

-- ============================================================
-- 3. 对话表
-- ============================================================
CREATE TABLE conversations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title           VARCHAR(255),
    model           VARCHAR(64) NOT NULL DEFAULT 'gpt-4o',
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_conv_user_id ON conversations (user_id);
CREATE INDEX idx_conv_updated_at ON conversations (updated_at DESC);
CREATE INDEX idx_conv_user_updated ON conversations (user_id, updated_at DESC);

-- ============================================================
-- 4. 消息表
-- ============================================================
CREATE TABLE messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            VARCHAR(16) NOT NULL
                    CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content         TEXT,
    prompt_tokens      INTEGER NOT NULL DEFAULT 0,
    completion_tokens  INTEGER NOT NULL DEFAULT 0,
    total_tokens       INTEGER NOT NULL DEFAULT 0,
    latency_ms         INTEGER,           -- 从请求到完成的总延迟 (ms)
    references_json    JSONB,             -- 知识库检索引用的文档片段
    tool_calls_json    JSONB,             -- Agent 工具调用记录
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_msg_conv_id ON messages (conversation_id);
CREATE INDEX idx_msg_created_at ON messages (created_at);
CREATE INDEX idx_msg_role ON messages (role);

-- ============================================================
-- 5. 操作日志表 (审计 & 大数据统计)
-- ============================================================
CREATE TABLE operation_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    request_id      VARCHAR(64),
    method          VARCHAR(10) NOT NULL,
    path            VARCHAR(512) NOT NULL,
    status_code     INTEGER NOT NULL,
    latency_ms      INTEGER NOT NULL,
    ip_address      VARCHAR(45),
    user_agent      VARCHAR(512),
    token_used      BOOLEAN NOT NULL DEFAULT FALSE,  -- 本次请求是否调用了 AI Token
    request_body    TEXT,         -- 脱敏后的请求体片段
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_oplog_user_id ON operation_logs (user_id);
CREATE INDEX idx_oplog_created_at ON operation_logs (created_at DESC);
CREATE INDEX idx_oplog_method_path ON operation_logs (method, path);
CREATE INDEX idx_oplog_status ON operation_logs (status_code);
CREATE INDEX idx_oplog_latency ON operation_logs (latency_ms);
CREATE INDEX idx_oplog_token ON operation_logs (token_used) WHERE token_used = TRUE;

-- 按日期分区加速时序查询 (可选)
-- CREATE INDEX idx_oplog_date ON operation_logs ((created_at::DATE));

-- ============================================================
-- 6. 触发器：自动更新 updated_at
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_file_metadata_updated_at
    BEFORE UPDATE ON file_metadata
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- 7. 统计视图 (为大数据看板预聚合)
-- ============================================================

-- 7a. 用户用量概览
CREATE OR REPLACE VIEW v_user_stats AS
SELECT
    u.id AS user_id,
    u.username,
    u.role,
    u.quota_used_bytes,
    u.quota_total_bytes,
    COUNT(DISTINCT c.id)      AS conversation_count,
    COUNT(DISTINCT f.id) FILTER (WHERE f.deleted_at IS NULL) AS file_count,
    COALESCE(SUM(m.total_tokens) FILTER (WHERE m.role = 'assistant'), 0) AS total_tokens_used,
    COUNT(DISTINCT m.id)      AS message_count,
    u.last_login_at
FROM users u
LEFT JOIN conversations c ON c.user_id = u.id
LEFT JOIN messages m ON m.conversation_id = c.id
LEFT JOIN file_metadata f ON f.uploaded_by = u.id
GROUP BY u.id;

-- 7b. 每日统计聚合
CREATE OR REPLACE VIEW v_daily_stats AS
SELECT
    DATE(created_at) AS stat_date,
    COUNT(*) FILTER (WHERE method = 'POST' AND path = '/api/v1/knowledge-base/chat') AS conversations,
    COUNT(*) AS total_requests,
    COUNT(*) FILTER (WHERE token_used = TRUE) AS ai_requests,
    AVG(latency_ms)::INTEGER AS avg_latency_ms,
    COUNT(*) FILTER (WHERE status_code >= 400) AS errors_count,
    COUNT(DISTINCT user_id) AS active_users
FROM operation_logs
GROUP BY DATE(created_at)
ORDER BY stat_date DESC;

-- ============================================================
-- 8. 种子数据 (开发/演示用)
-- ============================================================
INSERT INTO users (id, username, email, password_hash, role, quota_total_bytes) VALUES
(
    '00000000-0000-0000-0000-000000000001',
    'admin',
    'admin@cs.university.edu.cn',
    crypt('Admin@123456', gen_salt('bf', 10)),
    'admin',
    10737418240  -- 10GB for admin
),
(
    '00000000-0000-0000-0000-000000000002',
    'demo_user',
    'demo@cs.university.edu.cn',
    crypt('Demo@123456', gen_salt('bf', 10)),
    'user',
    1073741824
) ON CONFLICT (id) DO NOTHING;
