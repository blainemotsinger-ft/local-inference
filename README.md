# local-inference

Run a capable local coding worker and farm bounded tasks to it from OpenCode or
Claude Code. The lead agent writes the task, the local worker does it, and the
lead verifies the diff and tests before anything is committed.

## What this is

- **Colibri** — a pure-C hierarchical inference engine. The dense part and hot
  experts stay in RAM/VRAM; cold experts stream from disk.
- **Qwen3.6-35B-A3B** by default — 35B total, 3B active. Any model on
  Colibri's list can be installed instead, such as Qwen3-Coder-30B-A3B (30B
  total, 3B active, no thinking). See "Choosing a model" below.
- **OpenCode provider `colibri`** — OpenAI-compatible endpoint at
  `http://127.0.0.1:8000/v1`, model `qwen3.6-colibri` or
  `qwen3-coder-30b-a3b-colibri`.
- **OpenCode subagent `local-worker`** — a bounded worker with edit and shell
  access, but no push, commit, rebase, or `rm`.
- **`/farm`** — a command that delegates a task to `local-worker` and requires
  the lead to verify the result.
- **Claude Code `/farm`** — the same flow with Claude as the lead. The worker
  is a headless Claude Code process pointed at Colibri's Anthropic-compatible
  endpoint (`/v1/messages`), with the same denied commands. See
  `docs/claude-code.md`.
- **`scripts/claude-colibri.sh`** — a whole Claude Code session on the local
  model.
- **Colibri MCP server** — registered in Claude Code so Claude can check,
  start, and stop Colibri.

## Measured on the reference box

| Setup | Decode | Warm start |
|---|---|---|
| CPU only, 64K | 0.27 tok/s | ~6 min |
| GTX 1070, Vulkan, 64K | 22.4 tok/s | 374 s (HDD) |
| GTX 1070, Vulkan, 128K | 21.0-21.7 tok/s | 400 s (HDD), 39 s (SSD) |

A 256-token coding answer took 11.8 s at 128K on the SSD. These are one
machine's numbers, not a guarantee. See `docs/benchmarks.md`.

## Requirements

- Linux. Debian/Ubuntu tested.
- 16 GB RAM minimum, 32 GB recommended.
- A Vulkan GPU with ~8 GB (GTX 1070 tested) or CPU-only.
- ~25 GB free disk for the model.
- `git`, `python3`, `make`, `gcc`.
- For Vulkan: `sudo apt install libvulkan-dev glslc mesa-vulkan-drivers`.

## Install

```bash
scripts/install-colibri.sh
```

This clones Colibri, builds its engine, and downloads Qwen3.6-35B-A3B (23 GB).
It does not start the server. A download that stops partway continues where
it left off when you run the script again. Then start it detached:

```bash
scripts/start-colibri.sh
```

### Choosing a model

Pass a model id from Colibri's list to install another one:

```bash
scripts/install-colibri.sh --list             # the models and whether they fit this machine
scripts/install-colibri.sh qwen3-coder-30b    # 19 GB; code and tool calls, no thinking
```

Colibri serves one model at a time: the one installed last. Run the script
again to switch, then restart Colibri (`coli stop`, then
`scripts/start-colibri.sh`). A model already downloaded is not downloaded
again.

| Model | Install id | API model id | Download |
|---|---|---|---|
| Qwen3.6-35B-A3B | `qwen36-35b` | `qwen3.6-colibri` | 23 GB |
| Qwen3-Coder-30B-A3B | `qwen3-coder-30b` | `qwen3-coder-30b-a3b-colibri` | 19 GB |

### Context window

By default Colibri picks the context window from the memory it finds. On a
laptop with an 8 GB RTX 2000 Ada and 64 GB of RAM it picks 65536 tokens for
Qwen3.6. To ask for a fixed size instead:

```bash
scripts/install-colibri.sh qwen36-35b --ctx 131072
```

A larger window needs more memory. `--ctx 0` goes back to automatic. Check
what the server is actually serving with:

```bash
curl -s -H "x-api-key: local" http://127.0.0.1:8000/v1/models   # context_length
```

The Claude Code scripts read the model and the window from the server, so
they follow whatever you install. OpenCode cannot, so its provider file sets
the window by hand; see the comment at the top of
`opencode/providers/colibri.jsonc`.

### GPU memory

The GPU holds two things that compete for its memory: cached model weights,
and the conversation so far (the model's attention cache). By default
Colibri fills nearly the whole card with weights. The conversation starts
small and grows as the worker reads files and runs commands; when it needs
more room, Colibri takes it back from the cached weights.

On an 8 GB card that is where things go wrong. After a few of those growths,
Colibri moves weights onto the CPU and the model slows down by a factor of
about 35: one generated token went from about 50 ms to 1,757 ms. A worker
step that took 11 seconds then runs past Claude Code's 10-minute limit, and
the engine stays slow until Colibri is restarted. In testing, two worker runs
out of two did this, at about 13,000 and 15,000 tokens of conversation.

The fix is to cap the weights, so the conversation has room to grow without
taking any back. Set it when you install:

```bash
scripts/install-colibri.sh qwen36-35b --gpu-cache 2.5
```

The installer saves it in Colibri's own saved settings (`COLI_VK_TIER_GB` in
`~/.local/share/colibri/setup.json`), so it applies however Colibri starts:
`scripts/start-colibri.sh`, `coli start`, or Claude asking Colibri's MCP
server to start it. No shell profile needed. Installing again, for example to
switch models, keeps it; `--gpu-cache auto` removes it and lets Colibri decide.
On an NVIDIA card with 8 GB or less and no cap set, the installer prints this
suggestion but does not apply it.

Colibri reads the cap only when the server starts, so stop a running server
first (`coli stop`). `scripts/start-colibri.sh` says which cap applies. To try
another value for one start without saving it:

```bash
COLIBRI_GPU_CACHE_GB=2 scripts/start-colibri.sh
```

To size it: Colibri logs each growth of the conversation memory to
`~/.local/share/colibri/logs/serve.log` as `the KV mirror grows from ... (...
MiB of them from the expert tier)`. If that second number is above 0, lower
the cap. Qwen3.6 needs about 20 KB of GPU memory per token of conversation,
so 64K tokens need about 1.3 GB.

Measured on a laptop with an RTX 2000 Ada (8 GB), 64 GB of RAM, Qwen3.6, 64K
context:

| | Colibri's default (4.39 GiB of weights) | `--gpu-cache 2.5` |
|---|---|---|
| Chat, 7 turns after the first | 25.6 tok/s | 18.8 tok/s |
| `/farm` worker, 43 shellcheck fixes in 4 scripts | slowed to a crawl after 4 minutes, at 15,000 tokens; no result | finished in 5 min 59 s, 28 turns, every check passing |

The cap costs about a quarter of the chat speed. For the worker, where the
conversation keeps growing, it is the difference between finishing and not.

Qwen3-Coder-30B-A3B does worse on that card even with the cap. It keeps its
attention cache in all 48 of its layers, where Qwen3.6 keeps it in 10 of 40,
so each token of conversation takes about 98 KB rather than 20 KB. Colibri
gives it 32K of context instead of 64K, it chatted at 12.1 tok/s, and its
worker run filled the card and slowed to a crawl at about 11,000 tokens
without finishing. On a card with more memory the comparison may come out
differently.

Wire OpenCode:

```bash
scripts/bootstrap-opencode.sh
```

The bootstrap copies the agent and command into `~/.config/opencode/` and prints
the provider snippet. OpenCode has no config includes, so merge
`opencode/providers/colibri.jsonc` into the `providers` object of
`~/.config/opencode/opencode.jsonc` once.

Set the endpoint variables in your shell profile:

```bash
export COLIBRI_BASE_URL=http://127.0.0.1:8000/v1
export COLIBRI_API_KEY=local
```

If the server is on another machine, point `COLIBRI_BASE_URL` at it.

Wire Claude Code:

```bash
scripts/bootstrap-claude.sh
```

This copies the `/farm` skill into `~/.claude/skills/`, links
`claude-local-worker` into `~/.local/bin`, and registers Colibri's MCP server.
It reads the same `COLIBRI_BASE_URL` and `COLIBRI_API_KEY`, and asks the
server which model it serves and how large its context window is. Do not set
`COLIBRI_MODEL` or `COLIBRI_CONTEXT` in your profile: they are only
overrides, and the scripts refuse a model the server is not serving or a
window larger than the server's. See `docs/claude-code.md` for the details.

## Use

The command is the same in OpenCode and Claude Code:

```
/farm add a test for Select in internal/balancer, run go test ./internal/balancer
```

The lead expands the task, hands it to the local worker, then:

1. reads the diff and every changed file;
2. runs the named tests and quotes the output;
3. accepts and commits only if it passes.

The worker cannot commit or push. The lead owns the merge.

In Claude Code, watch the worker's steps as it takes them from another
terminal:

```bash
tail -F ~/.local/state/claude-local-worker/latest.log
```

To run a whole Claude Code session on the local model instead:

```bash
scripts/claude-colibri.sh
```

Its first request is slow. The local model has to read Claude Code's full
system prompt and tool list before it answers; see `docs/claude-code.md`.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests check the Claude Code scripts against `tests/fake_colibri.py`, a
fake Colibri server that plays back scripted model answers. No model, GPU, or
network is needed, and the run takes a few seconds. They check that the worker
is refused `git push`, `git commit`, `git rebase`, and `rm`; that it can
create, edit, and search files; and that every request goes to the local model
with the local key. Tests that start Claude Code are skipped when `claude` is
not installed. Each test uses its own git repository and `CLAUDE_CONFIG_DIR`,
so your `~/.claude` is not touched.

They do not test the model's work or Colibri itself. Run a real `/farm` task
for that.

## What to commit

- `opencode/agents/local-worker.md`
- `opencode/commands/farm.md`
- `opencode/providers/colibri.jsonc`
- `claude/`
- `tests/`
- `scripts/`
- `docs/`
- `.gitignore`

## What not to commit

- Model weights (23 GB), `.coli_usage`, logs, pidfiles.
- `~/.local/share/colibri/setup.json` (machine paths).
- API keys. Use `{env:...}` and never paste a key into the repo.
- Your full `~/.config/opencode/opencode.jsonc` if it contains other providers'
  secrets.

## Safety

`local-worker` can edit files and run shell commands for tests. It is denied
`git push`, `git commit`, `git rebase`, and `rm`. For risky work, run the worker
in a git worktree and review before merging.

The Claude Code worker has the same denials, set in
`claude/local-worker-settings.json`. It loads none of your own Claude Code
settings, hooks, plugins, or MCP servers.

## Licence

MIT. See `LICENSE`.
