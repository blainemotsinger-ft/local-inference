# Claude Code

Colibri serves an Anthropic-compatible endpoint, `/v1/messages`, on the same
port as the OpenAI one. Claude Code talks to it directly, with no proxy in
between. See Colibri's
[`docs/api.md`](https://github.com/JustVugg/colibri/blob/main/docs/api.md).

This repo gives you three ways to use it from Claude Code:

| Setup | Lead | Worker | Use it for |
|---|---|---|---|
| `/farm` | Claude, on your Anthropic account | Qwen3.6 on Colibri | Handing bounded tasks to the local model while Claude checks the result |
| `scripts/claude-colibri.sh` | Qwen3.6 on Colibri | none | A whole Claude Code session that never leaves the machine |
| Colibri MCP server | Claude | none | Letting Claude check, start, and stop Colibri |

## Install

Install and start Colibri first; see the README. Then:

```bash
scripts/bootstrap-claude.sh
```

It does three things:

1. Copies the `/farm` skill to `~/.claude/skills/farm/SKILL.md`.
2. Links `~/.local/bin/claude-local-worker` to `scripts/claude-local-worker.sh`.
   `~/.local/bin` must be on your `PATH`.
3. Registers Colibri's MCP server at user scope, if Colibri is installed at
   `$COLIBRI_HOME` and no server named `colibri` is registered yet:

   ```bash
   claude mcp add --scope user colibri -- python3 "$COLIBRI_HOME/c/coli" mcp
   ```

`CLAUDE_CONFIG_DIR` and `BIN_DIR` override the two destinations.

## Settings

All of them have defaults, so nothing needs to be set when Colibri runs on this
machine on port 8000.

| Variable | Default | What it is |
|---|---|---|
| `COLIBRI_BASE_URL` | `http://127.0.0.1:8000/v1` | The OpenAI-style URL OpenCode also uses. The scripts strip `/v1` for Claude Code. |
| `COLIBRI_API_KEY` | `local` | Any non-empty value. Colibri checks it only when the server sets `COLI_API_KEY`. |
| `COLIBRI_MODEL` | `qwen3.6-colibri` | The model id `coli status` prints. |
| `COLIBRI_CONTEXT` | `131072` | The context window Colibri serves. Claude Code compacts the conversation at this size. |

`scripts/colibri-claude-env.sh` turns these into the Claude Code variables:

| Claude Code variable | Set to | Why |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `COLIBRI_BASE_URL` without `/v1` | Sends requests to Colibri |
| `ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` | `COLIBRI_MODEL` | Every request uses the local model id, including background requests |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `COLIBRI_MODEL` | Subagents use the local model too |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `COLIBRI_CONTEXT` | Claude Code does not know the local model id and would assume 200K tokens, compact too late, and get `context_length_exceeded` from Colibri |
| `API_TIMEOUT_MS` | `600000` | The first request of a session can take minutes on a local model |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | No telemetry or update checks from a local session |

## `/farm`: Claude leads, Qwen works

```
/farm add a test for Select in internal/balancer, run go test ./internal/balancer
```

Claude, the lead:

1. Writes a self-contained brief: goal, files, test command, and what done
   looks like. The worker cannot see your conversation.
2. Runs `claude-local-worker "<brief>"`. This starts a second, headless Claude
   Code process pointed at Colibri, which edits files in the current directory
   and prints a report.
3. Reads `git diff` and every changed file, runs the tests, and quotes the
   output.
4. Reports, fixes the failure itself, or runs the worker once more with the
   failure in the brief.

Nothing is committed or pushed without asking you.

You can also run the worker yourself:

```bash
claude-local-worker "add a test for Select in internal/balancer, run go test ./internal/balancer"
```

### What the worker can and cannot do

The worker runs with `claude/local-worker-settings.json` and nothing else:

- **Tools:** `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash`. No web access, no
  subagents, no MCP servers.
- **Denied:** `git push`, `git commit`, `git rebase`, and `rm`. Claude Code
  also checks each part of a combined command, so `cd x && git commit` is
  denied too.
- **Your settings do not apply.** `--setting-sources ""` skips your user,
  project, and local settings, so your hooks, plugins, and permission rules
  are not loaded into the worker.
- **System prompt:** `claude/local-worker.md`, about 1,100 characters, in place
  of Claude Code's full prompt. A small first request matters on a local
  model; see "Speed" below.

It does not use `--bare`. In Claude Code 2.1.318, `--bare` limits the tools to
`Bash`, `Edit`, and `Read`, and without `Write` the worker cannot create a new
file such as a new test.

For risky work, run the lead in a git worktree so the worker's edits stay out
of your main checkout.

## `scripts/claude-colibri.sh`: everything on Qwen

```bash
scripts/claude-colibri.sh                  # interactive
scripts/claude-colibri.sh -p "explain internal/balancer/select.go"
```

Arguments pass straight to `claude`. This is your normal Claude Code (your
settings, hooks, CLAUDE.md, MCP servers), but every request goes to Colibri.
It sends the key as a bearer token, not `ANTHROPIC_API_KEY`, so a Claude Code
that is logged in to a claude.ai account does not stop to ask which credential
to use.

Expect it to be slow to start. See "Speed".

## Colibri MCP server

`coli mcp` is a stdio MCP server with these tools: `detect_hardware`,
`recommend_models`, `install`, `start`, `stop`, `status`, and `logs`. Once it is
registered, you can ask Claude "is Colibri running?" or "start Colibri" from any
session. See Colibri's
[`docs/MCP_SERVER.md`](https://github.com/JustVugg/colibri/blob/main/docs/MCP_SERVER.md).

## Speed

Colibri's docs warn that Claude Code is the client hit hardest by slow prompt
processing: "its system prompt and tool catalog are large." Before the first
token comes back, the local model has to read all of it.

- Colibri keeps the processed start of the prompt between requests, so only
  the first request of a session pays the full cost. Later turns process only
  what is new.
- Colibri sends a keepalive every 10 seconds while it works, so Claude Code
  does not give up. A session that looks stuck on its first request is usually
  still processing.
- The `/farm` worker sends a short system prompt and six tools for this reason.
  `scripts/claude-colibri.sh` sends Claude Code's full prompt and all your
  tools and MCP servers, so its first request is much larger.

## Expected messages

- `[claude-code:unrecognized_model] {"model":"qwen3.6-colibri",...}` on stderr.
  Claude Code does not know the local model id. It is harmless.
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS` already supplies the window it would
  otherwise guess.
- `claude.ai connectors are disabled because ANTHROPIC_API_KEY ... is set`
  from the worker. The worker uses the local key, not your claude.ai login,
  so your organization's connectors are not loaded into it. That is intended.

## Files

| File | What it is |
|---|---|
| `claude/skills/farm/SKILL.md` | The `/farm` skill, copied into `~/.claude/skills/` |
| `claude/local-worker.md` | The worker's system prompt |
| `claude/local-worker-settings.json` | The worker's permissions |
| `scripts/claude-local-worker.sh` | Runs one worker task, linked as `claude-local-worker` |
| `scripts/claude-colibri.sh` | Runs a whole Claude Code session on Colibri |
| `scripts/colibri-claude-env.sh` | The shared settings above, sourced by both scripts |
| `scripts/bootstrap-claude.sh` | Installs the skill, the link, and the MCP server |
