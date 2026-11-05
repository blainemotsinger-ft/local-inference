# Claude Code

Colibri serves an Anthropic-compatible endpoint, `/v1/messages`, on the same
port as the OpenAI one. Claude Code talks to it directly, with no proxy in
between. See Colibri's
[`docs/api.md`](https://github.com/JustVugg/colibri/blob/main/docs/api.md).

This repo gives you three ways to use it from Claude Code:

| Setup | Lead | Worker | Use it for |
|---|---|---|---|
| `/farm` | Claude, on your Anthropic account | The local model on Colibri | Handing bounded tasks to the local model while Claude checks the result |
| `scripts/claude-colibri.sh` | The local model on Colibri | none | A whole Claude Code session that never leaves the machine |
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

Nothing needs to be set when Colibri runs on this machine on port 8000.
Before Claude Code starts, both scripts ask Colibri's `/v1/models` which model
it is serving and how large its context window is, and use those.

| Variable | Default | What it is |
|---|---|---|
| `COLIBRI_BASE_URL` | `http://127.0.0.1:8000/v1` | The OpenAI-style URL OpenCode also uses. The scripts strip `/v1` for Claude Code. |
| `COLIBRI_API_KEY` | `local` | Any non-empty value. Colibri checks it only when the server sets `COLI_API_KEY`. |
| `COLIBRI_MODEL` | the server's model | An override. It must match the model Colibri is serving, because Colibri answers only to that one; otherwise the scripts stop with an error. |
| `COLIBRI_CONTEXT` | the server's `context_length` | An override. It may be smaller than the server's window, which makes Claude Code compact sooner, but never larger; otherwise the scripts stop with an error. |
| `CLAUDE_LOCAL_WORKER_LOGS` | `~/.local/state/claude-local-worker` | Where the worker writes its logs. |

Do not keep `COLIBRI_MODEL` or `COLIBRI_CONTEXT` in your shell profile. A fixed
value goes stale the next time you install another model or Colibri picks
another window, and the scripts will refuse to start until it is removed.

`colibri_configure` in `scripts/colibri-claude-env.sh` turns these into the
Claude Code variables:

| Claude Code variable | Set to | Why |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `COLIBRI_BASE_URL` without `/v1` | Sends requests to Colibri |
| `ANTHROPIC_MODEL` and `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` | `COLIBRI_MODEL` | Every request uses the local model id, including background requests |
| `CLAUDE_CODE_SUBAGENT_MODEL` | `COLIBRI_MODEL` | Subagents use the local model too |
| `CLAUDE_CODE_MAX_CONTEXT_TOKENS` | `COLIBRI_CONTEXT` | Claude Code does not know the local model id and would assume 200K tokens, compact too late, and get `context_length_exceeded` from Colibri. Telling it more than the server serves does the same, which is why the override can only go down. |
| `API_TIMEOUT_MS` | `600000` | The first request of a session can take minutes on a local model |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | No telemetry or update checks from a local session |

## `/farm`: Claude leads, the local model works

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

### Watching the worker

The worker prints only its final report. Every step it takes goes to a log as
it happens. Follow the latest run from another terminal:

```bash
tail -F ~/.local/state/claude-local-worker/latest.log
```

Parts of a real run, with `[...]` where lines are left out:

```
task:    Goal: fix two shellcheck style warnings in the shell scripts in scripts/ without changing behavior.
[...]
folder:  /home/blaine/git/local-inference
model:   qwen3.6-colibri, 65536 tokens of context, at http://127.0.0.1:8000
started: 2026-11-05 14:16:52

14:16:52  start   model qwen3.6-colibri in /home/blaine/git/local-inference
14:17:08  says
                  I'll start by reading the shell scripts and understanding the current state of warnings.
14:17:08  Glob    scripts/*.sh
[...]
14:21:24  says
                  Now fix **claude-colibri.sh**:
14:21:24  Edit    /home/blaine/git/local-inference/scripts/claude-colibri.sh
                  - . "$ROOT/scripts/colibri-claude-env.sh"
                  + . "${ROOT}/scripts/colibri-claude-env.sh"
14:21:32  Edit    /home/blaine/git/local-inference/scripts/claude-colibri.sh
                  - export ANTHROPIC_AUTH_TOKEN="$COLIBRI_API_KEY"
                  + export ANTHROPIC_AUTH_TOKEN="${COLIBRI_API_KEY}"
[...]
14:21:59  Bash    $ shellcheck -x scripts/*.sh 2>&1; echo "EXIT CODE: $?"
                  EXIT CODE: 0
[...]
14:22:51  done    finished after 28 turns in 5m59s
```

Each line is one step: a file read, an edit with the lines it removes (`-`)
and adds (`+`), a command and its output, or what the model says. Output
longer than 12 lines is cut, and a line starting `!` is an error. The time on
each line is when the step happened, so a long gap is the model working, and
a gap that never ends is a stuck request.

Each run writes two files in `~/.local/state/claude-local-worker/`:
`<time>-<pid>.log`, the readable log above, and `<time>-<pid>.jsonl`, Claude
Code's own record of every step in full (`claude -p --output-format
stream-json --verbose`). `latest.log` links to the newest run. Old runs are
not deleted.

`scripts/claude-local-worker-log.pl` turns the record into the readable log.
It is Perl with only `JSON::PP`, which every Perl install has. Perl's JSON
reader is slow next to a compiled one, about 3 MB/s, but a run cannot produce
much: everything the worker sees has to fit in the model's context window, so
a run's record is around a megabyte, a fraction of a second of work spread
over minutes of model time.

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

## `scripts/claude-colibri.sh`: everything on the local model

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
- A worker that was making steps every 10 seconds or so and then stops for
  minutes, partway through, is usually out of GPU memory: the conversation
  grew and Colibri moved model weights off the card to make room. Claude Code
  gives up after 10 minutes and retries, and Colibri answers the retries with
  `429` until the old request ends. Check
  `~/.local/share/colibri/logs/serve.log` for `the KV mirror grows`, and see
  "GPU memory" in the README for `--gpu-cache`.
- The `/farm` worker sends a short system prompt and six tools for this reason.
  `scripts/claude-colibri.sh` sends Claude Code's full prompt and all your
  tools and MCP servers, so its first request is much larger.

## Expected messages

- `[claude-code:unrecognized_model] {"model":"qwen3.6-colibri",...}` on stderr.
  Claude Code does not know the local model id. It is harmless.
  `CLAUDE_CODE_MAX_CONTEXT_TOKENS` already supplies the window it would
  otherwise guess.
- `worker log: tail -F ...` on stderr from the worker. It says where to
  follow the run.
- `claude.ai connectors are disabled because ANTHROPIC_API_KEY ... is set`
  from the worker. The worker uses the local key, not your claude.ai login,
  so your organization's connectors are not loaded into it. That is intended.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

`tests/fake_colibri.py` stands in for Colibri. It answers `/v1/models` and
`/v1/messages` in Anthropic's format and, instead of running a model, plays
back a script of tool calls and answers. It records every request, so the tests
can check what Claude Code actually sent and what each tool call returned.

`tests/test_claude.py` covers:

| Test | What it checks |
|---|---|
| `WorkerPermissions` | `git push`, `git commit`, `git rebase`, `rm`, and `cd . && git commit` are all refused and nothing is committed or deleted; `Write`, `Edit`, `Glob`, `Grep`, and `Bash` work |
| `WorkerRequests` | Every request uses the local model id and the `local` key; the worker gets its six tools and no web tools; the task text arrives unchanged, quotes and `$` included; it still uses the local key when started from a logged-in Claude Code session; it uses the model and window the server reports, and refuses a `COLIBRI_MODEL` the server is not serving or a `COLIBRI_CONTEXT` larger than the server's |
| `WorkerLog` | stdout is only the final report; the readable log has the task, model, window, each step, and the finish line; the full record ends with the result; each run gets its own log and `latest.log` points at the newest |
| `LogFormatter` | A record with no final report exits 1; long output is cut at 12 lines; a line that is not JSON is kept |
| `WorkerErrors` | No task gives a usage message and exit 2; Colibri not running gives exit 1 |
| `SessionScript` | `claude-colibri.sh` sends a bearer token, not your own API key |
| `EnvFile` | `COLIBRI_BASE_URL` with or without `/v1` and a trailing `/`; the model and window come from the server; `COLIBRI_MODEL` must match it; `COLIBRI_CONTEXT` may be smaller, never larger, and must be a number; a server that reports no window needs `COLIBRI_CONTEXT` |
| `StartScript` | `start-colibri.sh` says which GPU cache cap applies (Colibri's choice, the saved one, or `COLI_VK_TIER_GB`), passes `COLIBRI_GPU_CACHE_GB` to Colibri for one start, and refuses a value that is not a number; checked against a fake `coli` |
| `InstallScript` | `install-colibri.sh` passes the model and context to `coli setup`; saves `--gpu-cache` in Colibri's settings and keeps it when an install without the flag rebuilds them; `--gpu-cache auto` removes it; bad arguments stop before setup runs; suggests a cap on an 8 GB NVIDIA card without applying it; stops if Colibri's settings are not in the expected shape. Against a fake Colibri and a fake `nvidia-smi` |
| `Bootstrap` | The skill is copied, the link points at the worker, and the MCP server is registered once |

Run the fake by hand to try the scripts without a model:

```bash
python3 tests/fake_colibri.py --port 8000 --log requests.jsonl
claude-local-worker "say done"      # in another terminal
```

`--script steps.json` takes a JSON list of steps, each
`{"tool": "Bash", "input": {"command": "..."}}` or `{"text": "final answer"}`.
Without it, the fake answers `done`. `--model-id` and `--context` set what
its `/v1/models` reports (default `qwen3.6-colibri` and 131072).

These tests caught three problems while the scripts were being written:
`--tools` took the task text as another tool name, `--bare` removed `Write`,
and Claude Code assumed a 200K context window for the local model. Rerun them
after updating Claude Code. A new version that renames a tool or changes a flag
fails here first.

## Files

| File | What it is |
|---|---|
| `claude/skills/farm/SKILL.md` | The `/farm` skill, copied into `~/.claude/skills/` |
| `claude/local-worker.md` | The worker's system prompt |
| `claude/local-worker-settings.json` | The worker's permissions |
| `scripts/claude-local-worker.sh` | Runs one worker task, linked as `claude-local-worker` |
| `scripts/claude-local-worker-log.pl` | Turns the worker's step-by-step record into the readable log |
| `scripts/colibri-gpu-cache.pl` | Reads and writes the GPU cache cap in Colibri's saved settings, for the install and start scripts |
| `scripts/claude-colibri.sh` | Runs a whole Claude Code session on Colibri |
| `scripts/colibri-claude-env.sh` | The shared settings above and `colibri_configure`, sourced by both scripts |
| `scripts/bootstrap-claude.sh` | Installs the skill, the link, and the MCP server |
| `tests/fake_colibri.py` | The fake Colibri server |
| `tests/test_claude.py` | The tests |
