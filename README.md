# WisdomChannel — WeChat Channel for Claude Code

A [Claude Code channel plugin](https://code.claude.com/docs/en/channels) that
pushes WeChat desktop messages into your running Claude Code session, and lets
Claude reply back through the same chat — like the official Telegram, Discord,
and iMessage channels.

It is the client side of the [Wisdom](https://github.com/AceDataCloud/Wisdom)
WeChat automation service: Wisdom runs on the Windows host with WeChat desktop
and exposes an HTTP + WebSocket API; this MCP server runs locally next to
Claude Code and bridges the two.

```
┌──────────────────┐      ┌────────────────┐      ┌────────────────┐
│  WeChat desktop  │      │  Wisdom API    │      │ wisdom_channel │      ┌──────────────┐
│  (Windows host)  │ ───► │  HTTP + WS     │ ───► │  (this repo)   │ ───► │ Claude Code  │
│  + Frida hooks   │      │  :8000         │      │  stdio MCP     │      │  CLI session │
└──────────────────┘      └────────────────┘      └────────────────┘      └──────────────┘
```

## Features

- Push every inbound WeChat message into the active Claude Code session
- Claude replies through the `reply` tool — answer goes back into WeChat
- Works for both private DMs and group chats (only forwards `@you` mentions in groups)
- Allowlist + admin trust levels (`access.json`)
- Tools: `reply`, `list_contacts`, `list_conversations`, `get_messages`,
  `get_status`, `manage_access`
- Talks to a **remote** Wisdom server over HTTP/WebSocket — Wisdom does not have
  to run on the same machine as Claude Code

## Requirements

- Python 3.10+
- A running [Wisdom](https://github.com/AceDataCloud/Wisdom) server with WeChat
  desktop logged in (any reachable host)
- [Claude Code CLI](https://code.claude.com/docs/en/quickstart) v2.1.80+

## Install

```powershell
pip install wisdom-channel
```

This installs the `wisdom-channel` console script. To develop from source instead:

```powershell
git clone https://github.com/AceDataCloud/WisdomChannel.git
cd WisdomChannel
pip install -e .
```

## Configure

Create the channel state directory and an `.env` pointing at your Wisdom server:

```powershell
mkdir "$env:USERPROFILE\.claude\channels\wechat" -Force

@"
WISDOM_API_URL=http://your-wisdom-host:8000
WISDOM_API_TOKEN=
WECHAT_BOT_NAME=
"@ | Set-Content "$env:USERPROFILE\.claude\channels\wechat\.env"
```

| Variable | Description |
|----------|-------------|
| `WISDOM_API_URL` | URL of the Wisdom REST API (default `http://localhost:8000`) |
| `WISDOM_API_TOKEN` | Optional bearer token if Wisdom auth is enabled |
| `WECHAT_BOT_NAME` | Your WeChat display name (auto-detected if empty) |
| `WECHAT_CONTEXT_MESSAGES` | Recent messages pulled as conversation context per reply (default `8`, `0` disables) |

Optional access control at `~/.claude/channels/wechat/access.json`:

```json
{
  "policy": "allowlist",
  "allowFrom": ["Alice", "Work Group"],
  "admins": ["Alice"]
}
```

| Policy | Behavior |
|--------|----------|
| `all` (default) | Forward every inbound message |
| `allowlist`     | Forward only senders in `allowFrom` / `admins` |
| `disabled`      | Drop everything |

`admins` are fully trusted — Claude executes their requests without confirmation.
`allowFrom` users get polite, read-only assistance.

## Run

The repo ships an `.mcp.json` that registers the channel as `wechat`:

```json
{
  "mcpServers": {
    "wechat": {
      "command": "python",
      "args": ["-m", "wisdom_channel"],
      "cwd": "."
    }
  }
}
```

Launch Claude Code with the channel from the project root:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."

claude --dangerously-skip-permissions `
       --dangerously-load-development-channels server:wechat
```

> **Run it in a persistent, interactive terminal** (a real TTY — e.g. an RDP
> session on the Wisdom host, `tmux`/`screen`, or a foreground terminal).
> Channels push inbound messages into a *live* Claude Code session, so the
> process must stay running and attached. Launched detached / without a TTY,
> Claude Code falls back to `--print` one-shot mode and exits immediately.
> `--channels` requires Claude Code **v2.1.80+**; the
> `--dangerously-load-development-channels` flag loads an unpublished
> (development) channel like this one.

What happens:

1. Claude Code reads `.mcp.json` and spawns `python -m wisdom_channel` over stdio
2. The channel loads `~/.claude/channels/wechat/.env` and probes Wisdom at `WISDOM_API_URL`
3. It connects to Wisdom's WebSocket and forwards inbound WeChat messages as
   `notifications/claude/channel`
4. Claude calls the `reply` tool, which posts to Wisdom's `/api/messages/send`
5. Wisdom drives WeChat desktop and the message is delivered

## Headless auto-reply (no Claude Code session)

The channel above needs a **persistent interactive Claude Code session**. For an
unattended host (no live terminal), run the bridge instead:

```powershell
wisdom-channel bridge            # optional: --model sonnet
```

It connects to the Wisdom WebSocket and, for each allowed inbound message,
shells out to `claude -p` and posts the reply back through Wisdom — the same
"WeChat in → Claude answers → WeChat out" loop, without a TTY. It honors the
same `access.json` allowlist and group @-mention gating. Requires the `claude`
CLI on `PATH`.

Each reply is built with **conversation context**: who sent it, which group,
who else was @-mentioned, the quoted ("引用") message, and the last
`WECHAT_CONTEXT_MESSAGES` messages — so answers follow the thread instead of
seeing each message in isolation. Admin (tool-bearing) mode is **private-chat
only**: in a group, anyone who @-mentions the bot gets chat-only access, even
admins.

## Standalone test

```powershell
python -m wisdom_channel --test
```

Exercises Wisdom REST + WebSocket without launching Claude Code.

## Logs

| What | Where |
|------|-------|
| Channel log | `~/.claude/channels/wechat/mcp.log` |
| Channel state | `~/.claude/channels/wechat/` |

## Related

- [Wisdom](https://github.com/AceDataCloud/Wisdom) — the WeChat automation backend
- [Claude Code channels documentation](https://code.claude.com/docs/en/channels)
- [Anthropic Telegram plugin](https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/telegram) — the reference design

## License

MIT — see [LICENSE](LICENSE).
