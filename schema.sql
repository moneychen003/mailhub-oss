-- mailhub schema
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;

-- 用户/员工账号
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  email TEXT,
  role TEXT NOT NULL DEFAULT 'user',           -- admin | user
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at TIMESTAMPTZ
);

-- 托管的域名 (9 个 CF 域 + 任意手动加的)
CREATE TABLE IF NOT EXISTS domains (
  id SERIAL PRIMARY KEY,
  domain TEXT NOT NULL UNIQUE,
  dkim_selector TEXT DEFAULT 'default',
  dkim_public_key TEXT,
  inbound_host TEXT,
  dkim_status TEXT DEFAULT 'pending',          -- pending | active | failed
  mx_status TEXT DEFAULT 'pending',
  spf_status TEXT DEFAULT 'pending',
  dmarc_status TEXT DEFAULT 'pending',
  receive_enabled BOOLEAN NOT NULL DEFAULT false,
  send_enabled BOOLEAN NOT NULL DEFAULT false,
  notes TEXT,
  last_checked_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 用户可用的发件人地址 (user 自定义 alias)
CREATE TABLE IF NOT EXISTS senders (
  id SERIAL PRIMARY KEY,
  email CITEXT NOT NULL UNIQUE,                -- ops@example.com
  display_name TEXT,                            -- "Ops Team"
  domain_id INT REFERENCES domains(id),         -- 用哪个域的 DKIM 签名
  signature_text TEXT,
  signature_html TEXT,
  is_default BOOLEAN NOT NULL DEFAULT false,
  created_by INT REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 全局站点配置。敏感密钥不要放这里；这里存展示名、站点 URL 等。
CREATE TABLE IF NOT EXISTS app_config (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 发信配置。mode=local_postfix 时走 127.0.0.1:25；mode=smtp 时走远端 SMTP。
CREATE TABLE IF NOT EXISTS smtp_config (
  id INT PRIMARY KEY DEFAULT 1,
  mode TEXT NOT NULL DEFAULT 'local_postfix',   -- local_postfix | smtp
  host TEXT,
  port INT NOT NULL DEFAULT 587,
  username TEXT,
  password TEXT,
  use_tls BOOLEAN NOT NULL DEFAULT false,
  use_starttls BOOLEAN NOT NULL DEFAULT true,
  enabled BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (id = 1)
);

-- IMAP 拉取来源。用于开源自部署时不必先配置 Postfix pipe。
CREATE TABLE IF NOT EXISTS imap_accounts (
  id BIGSERIAL PRIMARY KEY,
  label TEXT NOT NULL,
  host TEXT NOT NULL,
  port INT NOT NULL DEFAULT 993,
  username TEXT NOT NULL,
  password TEXT NOT NULL,
  mailbox TEXT NOT NULL DEFAULT 'INBOX',
  use_ssl BOOLEAN NOT NULL DEFAULT true,
  enabled BOOLEAN NOT NULL DEFAULT true,
  source TEXT,
  last_uid BIGINT,
  last_sync_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_imap_accounts_enabled ON imap_accounts(enabled, updated_at DESC);

-- 邮件线程
CREATE TABLE IF NOT EXISTS threads (
  id BIGSERIAL PRIMARY KEY,
  subject_initial TEXT,
  participants TEXT[] NOT NULL DEFAULT '{}',   -- 所有出现过的邮箱
  first_message_at TIMESTAMPTZ,
  last_message_at TIMESTAMPTZ,
  message_count INT NOT NULL DEFAULT 0,
  ai_priority TEXT,                             -- urgent | high | normal | low | spam
  ai_category TEXT,                             -- billing | order | support | marketing | personal | ...
  ai_summary TEXT,
  ai_action TEXT,                               -- AI 建议动作
  ai_classified_at TIMESTAMPTZ,
  ai_model TEXT,
  status TEXT NOT NULL DEFAULT 'inbox',         -- inbox | archived | trash | spam
  tags TEXT[] NOT NULL DEFAULT '{}',
  due_at TIMESTAMPTZ,                           -- 待办截止 (AI 解析出来或人工设的)
  reminded_at TIMESTAMPTZ,
  source TEXT,                                  -- live | 163 | qq | gmail-* | unknown
  flagged BOOLEAN NOT NULL DEFAULT false,
  pinned BOOLEAN NOT NULL DEFAULT false,
  pinned_at TIMESTAMPTZ,
  snoozed_until TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_threads_status_last ON threads(status, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_priority ON threads(ai_priority, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_due ON threads(due_at) WHERE due_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_threads_source ON threads(source, last_message_at DESC);
CREATE INDEX IF NOT EXISTS idx_threads_flagged ON threads(flagged, last_message_at DESC) WHERE flagged=true;
CREATE INDEX IF NOT EXISTS idx_threads_pinned ON threads(pinned, pinned_at DESC) WHERE pinned=true;
CREATE INDEX IF NOT EXISTS idx_threads_snoozed_until ON threads(snoozed_until) WHERE snoozed_until IS NOT NULL;

-- 邮件 (in + out 一张表)
CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  thread_id BIGINT REFERENCES threads(id) ON DELETE CASCADE,
  direction TEXT NOT NULL,                      -- in | out
  message_id TEXT,                              -- RFC822 Message-ID (去尖括号)
  in_reply_to TEXT,
  references_chain TEXT[],
  subject TEXT,
  from_email CITEXT,
  from_name TEXT,
  to_emails CITEXT[] NOT NULL DEFAULT '{}',
  cc_emails CITEXT[] NOT NULL DEFAULT '{}',
  bcc_emails CITEXT[] NOT NULL DEFAULT '{}',
  reply_to CITEXT,
  body_text TEXT,
  body_html TEXT,
  snippet TEXT,                                 -- 列表预览用
  raw_path TEXT NOT NULL,                       -- 原始 .eml 路径
  size_bytes INT,
  has_attachments BOOLEAN NOT NULL DEFAULT false,
  headers JSONB NOT NULL DEFAULT '{}',
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  parsed_at TIMESTAMPTZ,                        -- null = 待解析
  parse_status TEXT NOT NULL DEFAULT 'pending', -- pending | parsed | failed
  parse_error TEXT,
  sent_at TIMESTAMPTZ,                          -- outbound 实际发送时间
  sent_status TEXT,                             -- queued | sent | bounced | failed
  sent_error TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON messages(thread_id, received_at);
CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
CREATE INDEX IF NOT EXISTS idx_messages_in_reply_to ON messages(in_reply_to);
CREATE INDEX IF NOT EXISTS idx_messages_parse_status ON messages(parse_status) WHERE parse_status != 'parsed';
CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_email);
CREATE INDEX IF NOT EXISTS idx_messages_from_text_trgm ON messages USING gin ((from_email::text) gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_messages_from_name_trgm ON messages USING gin (from_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_messages_subject_trgm ON messages USING gin (subject gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_messages_snippet_trgm ON messages USING gin (snippet gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_messages_body_text_trgm ON messages USING gin (body_text gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_messages_body_html_trgm ON messages USING gin (body_html gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_threads_subject_initial_trgm ON threads USING gin (subject_initial gin_trgm_ops);

-- 附件
CREATE TABLE IF NOT EXISTS attachments (
  id BIGSERIAL PRIMARY KEY,
  message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  filename TEXT,
  content_type TEXT,
  size_bytes INT,
  disk_path TEXT,                               -- 落盘绝对路径
  content_id TEXT                               -- inline 用
);
CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_id);

-- 阅读/未读状态 (per-user)
CREATE TABLE IF NOT EXISTS thread_reads (
  thread_id BIGINT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (thread_id, user_id)
);

-- AI 端点配置 (单行 global, 后续可扩多 profile)
CREATE TABLE IF NOT EXISTS ai_config (
  id INT PRIMARY KEY DEFAULT 1,
  provider TEXT NOT NULL,                       -- openai | anthropic
  endpoint TEXT NOT NULL,                       -- e.g. https://api.openai.com/v1
  api_key TEXT NOT NULL,
  model TEXT NOT NULL,
  system_prompt TEXT,
  enabled BOOLEAN NOT NULL DEFAULT true,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (id = 1)
);

-- TG bot 配置
CREATE TABLE IF NOT EXISTS tg_config (
  id INT PRIMARY KEY DEFAULT 1,
  bot_token TEXT,
  chat_id TEXT,                                 -- @applecheckcard_bot 对应的 chat
  push_min_priority TEXT NOT NULL DEFAULT 'high', -- 大于等于此优先级推送
  enabled BOOLEAN NOT NULL DEFAULT false,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (id = 1)
);

-- AI 处理日志 (诊断用)
CREATE TABLE IF NOT EXISTS ai_jobs (
  id BIGSERIAL PRIMARY KEY,
  thread_id BIGINT REFERENCES threads(id) ON DELETE CASCADE,
  message_id BIGINT REFERENCES messages(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued',        -- queued | running | done | failed
  input_tokens INT,
  output_tokens INT,
  result JSONB,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_jobs(status, created_at) WHERE status IN ('queued','running');

-- 用户自定义分类规则
CREATE TABLE IF NOT EXISTS classification_rules (
  id BIGSERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id) ON DELETE CASCADE,
  scope TEXT NOT NULL,                         -- from_email | from_domain | subject_keyword
  value TEXT NOT NULL,
  force_priority TEXT NOT NULL,                -- urgent | high | normal | low | spam
  created_from_thread_id BIGINT REFERENCES threads(id) ON DELETE SET NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, scope, value)
);
CREATE INDEX IF NOT EXISTS idx_classification_rules_active
  ON classification_rules(user_id, active, scope, value);

-- 审计日志
CREATE TABLE IF NOT EXISTS events (
  id BIGSERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id),
  action TEXT NOT NULL,                         -- login | reply_sent | ai_config_updated | ...
  target_type TEXT,
  target_id BIGINT,
  payload JSONB,
  ip TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC);

-- 用户自定义文件夹
CREATE TABLE IF NOT EXISTS folders (
  id BIGSERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS thread_folders (
  thread_id BIGINT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  folder_id BIGINT NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(thread_id, folder_id)
);
CREATE INDEX IF NOT EXISTS idx_thread_folders_user ON thread_folders(user_id, folder_id);
CREATE INDEX IF NOT EXISTS idx_thread_folders_thread ON thread_folders(thread_id);

-- 邮件翻译缓存
CREATE TABLE IF NOT EXISTS message_translations (
  message_id BIGINT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  target TEXT NOT NULL,
  pairs JSONB NOT NULL,
  provider TEXT,
  model TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY(message_id, target)
);

-- 回复草稿
CREATE TABLE IF NOT EXISTS drafts (
  id BIGSERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id BIGINT REFERENCES threads(id) ON DELETE CASCADE,
  sender_id INT REFERENCES senders(id),
  to_emails CITEXT[] NOT NULL DEFAULT '{}',
  cc_emails CITEXT[] NOT NULL DEFAULT '{}',
  bcc_emails CITEXT[] NOT NULL DEFAULT '{}',
  subject TEXT,
  body_text TEXT,
  body_html TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(user_id, thread_id)
);
CREATE INDEX IF NOT EXISTS idx_drafts_user_updated ON drafts(user_id, updated_at DESC);

-- 回复模板
CREATE TABLE IF NOT EXISTS reply_templates (
  id BIGSERIAL PRIMARY KEY,
  user_id INT REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  active BOOLEAN NOT NULL DEFAULT true,
  use_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_reply_templates_active ON reply_templates(user_id, active, updated_at DESC);

-- 待发送附件(回信前先上传,发送成功后落到 attachments 表)
CREATE TABLE IF NOT EXISTS uploaded_attachments (
  id BIGSERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  content_type TEXT,
  size_bytes INT,
  disk_path TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  used_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_uploaded_attachments_user ON uploaded_attachments(user_id, created_at DESC);

-- 定时/撤销发送队列
CREATE TABLE IF NOT EXISTS scheduled_sends (
  id BIGSERIAL PRIMARY KEY,
  user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  thread_id BIGINT REFERENCES threads(id) ON DELETE CASCADE,
  sender_id INT NOT NULL REFERENCES senders(id),
  to_emails CITEXT[] NOT NULL DEFAULT '{}',
  cc_emails CITEXT[] NOT NULL DEFAULT '{}',
  bcc_emails CITEXT[] NOT NULL DEFAULT '{}',
  subject TEXT NOT NULL,
  body_text TEXT NOT NULL DEFAULT '',
  body_html TEXT,
  in_reply_to TEXT,
  references_chain TEXT[] NOT NULL DEFAULT '{}',
  attachment_ids BIGINT[] NOT NULL DEFAULT '{}',
  scheduled_for TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',       -- queued | sending | sent | cancelled | failed
  sent_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sent_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_scheduled_sends_due
  ON scheduled_sends(status, scheduled_for) WHERE status='queued';

-- 触发器: 更新 threads.message_count + last_message_at
CREATE OR REPLACE FUNCTION update_thread_stats() RETURNS TRIGGER AS $$
BEGIN
  UPDATE threads SET
    message_count = (SELECT count(*) FROM messages WHERE thread_id = NEW.thread_id),
    last_message_at = (SELECT max(received_at) FROM messages WHERE thread_id = NEW.thread_id),
    first_message_at = COALESCE(first_message_at, NEW.received_at)
  WHERE id = NEW.thread_id;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_messages_update_thread ON messages;
CREATE TRIGGER trg_messages_update_thread
AFTER INSERT ON messages
FOR EACH ROW EXECUTE FUNCTION update_thread_stats();
