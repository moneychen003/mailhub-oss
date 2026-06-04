# Mailhub

中文 | [English](#english)

Mailhub 是一个可自托管的 AI 邮件工作流系统。它不是另一个普通网页邮箱，而是把业务邮件变成可搜索、可分类、可协作、可自动化处理的工作台。

它可以通过 IMAP 拉取已有邮箱，也可以接收自有域名邮件，把邮件存入 Postgres，再用 AI 分类、总结、提取待办，并提供 Web 收件箱、回复、定时发送、规则、模板、签名、Telegram 推送和诊断面板。

## 为什么不是直接用传统邮箱？

传统邮箱，比如网易邮箱、QQ 邮箱、Gmail 这类产品，适合个人收发邮件。Mailhub 更适合团队、客服、订单、账单、采购、风控、运营等“邮件就是业务流”的场景。

| 场景 | 传统邮箱 | Mailhub |
|---|---|---|
| 多域名/多账号聚合 | 通常按个人邮箱或单账号管理 | 可以把多个 IMAP 来源或自有域名邮件汇入同一个工作台 |
| AI 分类和摘要 | 依赖邮箱厂商内置能力，难以自定义 | 可配置 OpenAI/Anthropic 兼容端点，自定义模型和提示词 |
| 业务优先级 | 主要靠星标、文件夹、人工筛选 | 支持 urgent/high/normal/low/spam 优先级和规则覆盖 |
| 团队处理 | 个人邮箱协作边界明显 | 支持用户、发件人身份、规则、模板、诊断等团队管理能力 |
| 自动化 | 难以接入自己的数据库和流程 | 邮件、线程、AI 任务、事件都在 Postgres 中，可二次开发 |
| 数据归属 | 数据在邮箱服务商体系内 | 自托管，数据、原始邮件和附件在自己的服务器上 |
| 可观测性 | 出问题通常只能看客户端现象 | 内置数据库、目录、SMTP、IMAP、AI 队列等诊断检查 |

一句话：传统邮箱解决“收发邮件”，Mailhub 解决“把邮件变成业务处理系统”。

## 适合谁？

- 有多个业务邮箱、域名或 catch-all 邮件入口的人
- 想把客户邮件、订单邮件、账单邮件自动分类的人
- 想用自己的 AI API 总结邮件和提取行动项的人
- 想把邮件数据留在自己服务器上的团队
- 想基于邮件做二次开发、统计、自动化和内部工具的人

## 功能

- 自托管 Docker Compose 部署
- 首次初始化页面和管理员创建
- IMAP 邮箱拉取
- 自有域名和 DNS 记录生成
- SMTP 或本机 Postfix 发信
- AI 分类、摘要、行动建议和截止时间提取
- Telegram 高优先级提醒
- 发件人身份和纯文本/HTML 签名
- 分类规则和回复模板
- 用户管理、诊断面板、运行状态检查
- Postgres 数据存储，方便备份和二次开发

## 示例图

### AI 收件箱 Demo

![Mailhub AI inbox demo](assets/screenshots/demo-inbox.jpg)

### 首次初始化

![Mailhub setup page](assets/screenshots/setup-page.jpg)

## 快速开始

```bash
git clone https://github.com/moneychen003/mailhub-oss.git
cd mailhub-oss
bash scripts/bootstrap.sh http://localhost:3024
```

打开：

```text
http://localhost:3024
```

如果 bootstrap 脚本生成了管理员密码，它会打印出来并写入 `.env`。如果没有预设管理员密码，打开 `http://localhost:3024/setup` 创建第一个管理员。

## 用 AI 帮你部署

如果你准备用 ChatGPT、Claude、Codex、Cursor、Kimi 等 AI 工具帮你部署 Mailhub，建议先让 AI 读取这些文件：

| 文件 | 用途 |
|---|---|
| `README.md` | 了解项目定位、功能和快速开始流程 |
| `SELF_HOSTING.md` | 了解生产部署、域名、SMTP、IMAP、AI、Telegram 和备份流程 |
| `.env.example` | 了解需要配置哪些环境变量 |
| `docker-compose.yml` | 了解服务组成、端口、数据卷和启动依赖 |
| `DEPLOY.md` | 了解一键 bootstrap 和部署后的检查步骤 |

你可以把下面这段直接发给 AI：

```text
请帮我部署这个 Mailhub 项目。先阅读 README.md、SELF_HOSTING.md、.env.example、docker-compose.yml 和 DEPLOY.md。

我的目标是：
1. 在服务器上用 Docker Compose 部署 Mailhub
2. 配置公开访问 URL
3. 创建第一个管理员
4. 配置域名 DNS、SMTP 发信、IMAP 收信
5. 配置 AI Provider 和 Telegram 推送
6. 最后打开 Settings -> Diagnostics，确认所有关键检查项

请你不要要求我把真实密码、API Key、邮箱应用专用密码直接发给你。
需要 secret 的地方，请先用占位符告诉我应该填什么，我会自己在服务器的 .env 或网页设置里填写。

请一步一步执行，并在每一步之后验证结果。
```

安全提醒：

- 不要把真实 `.env`、邮箱密码、AI API Key、Telegram Bot Token 发给公共 AI。
- 可以让 AI 读取 `.env.example`，但不要让 AI 读取已经填好真实密钥的 `.env`。
- 让 AI 帮你生成命令、检查日志、解释错误；真实 secret 最好由你自己粘贴到服务器或网页设置页。
- 部署完成后，在 Settings -> Diagnostics 检查数据库、目录、SMTP、IMAP 和 AI 队列状态。

## 自托管配置清单

所有常规配置都在 Settings 页面：

- 安装状态和目录可写检查
- 公开访问 URL 和收信主机名
- 域名和 DNS 记录
- SMTP 或本机 Postfix 发信
- IMAP 收信来源
- AI Provider 配置
- Telegram 推送配置
- 发件人身份和签名
- 分类规则和回复模板
- 用户管理和诊断检查

生产部署请看 [SELF_HOSTING.md](SELF_HOSTING.md)。

## 开发

后端：

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://mailhub:password@127.0.0.1:5432/mailhub
uvicorn app.main:app --port 8024
```

前端：

```bash
cd web
pnpm install
pnpm dev
```

## 数据安全

不要提交 `.env`、原始邮件、附件、私钥、Provider Token 或真实邮箱导出数据。

---

## English

Mailhub is a self-hosted AI mail workflow app. It is not just another webmail client. It turns business email into a searchable, classifiable, collaborative, and automatable workspace.

Mailhub can pull email from existing mailboxes over IMAP or receive mail for your own domains, store everything in Postgres, classify and summarize messages with an AI provider, and provide a web inbox with replies, scheduled sending, rules, templates, signatures, Telegram alerts, and diagnostics.

## Why Not Just Use Traditional Webmail?

Traditional mailboxes such as NetEase Mail, QQ Mail, and Gmail are great for personal email. Mailhub is designed for teams and workflows where email is part of operations: support, orders, billing, procurement, risk review, customer communication, and internal automation.

| Use case | Traditional webmail | Mailhub |
|---|---|---|
| Multiple domains/accounts | Usually account-centric | Aggregates multiple IMAP sources or hosted domains into one workspace |
| AI classification | Depends on provider features | Bring your own OpenAI/Anthropic-compatible endpoint, model, and prompt |
| Business priority | Mostly stars, folders, and manual triage | Built-in urgent/high/normal/low/spam priority plus custom rules |
| Team workflow | Personal mailbox boundaries | Users, sender identities, rules, templates, and diagnostics for operations |
| Automation | Hard to integrate with your own database | Threads, messages, AI jobs, and events live in Postgres |
| Data ownership | Data stays inside the mail provider | Self-hosted storage for raw mail, attachments, and metadata |
| Observability | Client-side symptoms only | Built-in checks for database, runtime paths, SMTP, IMAP, and AI queue state |

In short: traditional webmail helps you send and receive email. Mailhub helps you build an operational system around email.

## Who Is It For?

- People running multiple business mailboxes, domains, or catch-all addresses
- Teams that need automatic triage for customer, order, billing, or support email
- Builders who want to use their own AI API to summarize mail and extract actions
- Organizations that want mail data on their own server
- Developers who want to build internal tools and automations on top of email data

## Features

- Self-hosted Docker Compose deployment
- First-run setup page and admin creation
- IMAP mailbox sync
- Hosted domains and generated DNS records
- SMTP or local Postfix outbound delivery
- AI classification, summaries, action suggestions, and due-date extraction
- Telegram alerts for important messages
- Sender identities with plain-text and HTML signatures
- Classification rules and reply templates
- User management, diagnostics, and runtime checks
- Postgres storage for backup and custom development

## Screenshots

### AI Inbox Demo

![Mailhub AI inbox demo](assets/screenshots/demo-inbox.jpg)

### First-run Setup

![Mailhub setup page](assets/screenshots/setup-page.jpg)

## Quick Start

```bash
git clone https://github.com/moneychen003/mailhub-oss.git
cd mailhub-oss
bash scripts/bootstrap.sh http://localhost:3024
```

Open:

```text
http://localhost:3024
```

If the bootstrap script generated an admin password, it prints it and stores it in `.env`. If no admin password was configured, open `http://localhost:3024/setup` and create the first admin in the browser.

## Deploy With an AI Assistant

If you plan to use ChatGPT, Claude, Codex, Cursor, Kimi, or another AI tool to deploy Mailhub, ask it to read these files first:

| File | Purpose |
|---|---|
| `README.md` | Understand the project, feature set, and quick-start flow |
| `SELF_HOSTING.md` | Understand production deployment, domains, SMTP, IMAP, AI, Telegram, and backups |
| `.env.example` | Understand required environment variables |
| `docker-compose.yml` | Understand services, ports, volumes, and startup dependencies |
| `DEPLOY.md` | Understand the bootstrap command and post-deploy checks |

You can copy this prompt into your AI assistant:

```text
Please help me deploy this Mailhub project. First read README.md, SELF_HOSTING.md, .env.example, docker-compose.yml, and DEPLOY.md.

My goals are:
1. Deploy Mailhub on my server with Docker Compose
2. Configure the public URL
3. Create the first admin user
4. Configure domain DNS, SMTP sending, and IMAP receiving
5. Configure the AI provider and Telegram notifications
6. Open Settings -> Diagnostics and verify the important checks

Do not ask me to paste real passwords, API keys, mailbox app passwords, or bot tokens into this chat.
When a secret is required, tell me what placeholder to use and where I should enter the real value myself, either in .env or in the web settings page.

Proceed step by step and verify the result after each step.
```

Security notes:

- Do not send your real `.env`, mailbox password, AI API key, or Telegram bot token to a public AI assistant.
- It is safe to let AI read `.env.example`; do not let it read a filled production `.env`.
- Let AI generate commands, inspect logs, and explain errors; enter real secrets yourself on the server or in the web settings page.
- After deployment, check Settings -> Diagnostics for database, runtime paths, SMTP, IMAP, and AI queue status.

## Self-hosting Checklist

All routine setup lives in Settings:

- Installation status and writable path checks
- Public URL and inbound host
- Domains and DNS records
- SMTP or local Postfix outbound delivery
- IMAP inbound accounts
- AI provider configuration
- Telegram notification configuration
- Sender identities and signatures
- Classification rules and reply templates
- Users and diagnostics

See [SELF_HOSTING.md](SELF_HOSTING.md) for production deployment details.

## Development

Backend:

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://mailhub:password@127.0.0.1:5432/mailhub
uvicorn app.main:app --port 8024
```

Frontend:

```bash
cd web
pnpm install
pnpm dev
```

## Data Safety

Never commit `.env`, raw email, attachments, private keys, provider tokens, or real mailbox exports.

## 社区和联系 / Community

- Telegram 交流群 / Telegram Group: [https://t.me/+LTjvShD16aU5MDc1](https://t.me/+LTjvShD16aU5MDc1)
