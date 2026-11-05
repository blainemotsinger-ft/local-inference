# local-inference

Run a capable local coding worker and farm bounded tasks to it from OpenCode or
Claude Code. The lead agent writes the task, the local worker does it, and the
lead verifies the diff and tests before anything is committed.

## What this is

- **Colibri** — a pure-C hierarchical inference engine. The dense part and hot
  experts stay in RAM/VRAM; cold experts stream from disk.
- **Qwen3.6-35B-A3B** — 35B total, 3B active, 128K context in this setup.
- **OpenCode provider `colibri`** — OpenAI-compatible endpoint at
  `http://127.0.0.1:8000/v1`, model `qwen3.6-colibri`.
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

Then the one-time model download and first start (23 GB):

```bash
cd "${COLIBRI_HOME:-$HOME/git/JustVugg/colibri}"
./start-here.sh --model qwen36-35b \
  --dir "${COLIBRI_MODEL_DIR:-$HOME/colibri-models}" \
  --backend "${COLIBRI_BACKEND:-vulkan}" --yes
# wait for the dashboard, then:
./c/coli stop
```

After that, start it detached:

```bash
scripts/start-colibri.sh
```

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

If the server is on another machine, point `COLIBRI_BASE_URL` at it. The model
ID stays `qwen3.6-colibri` as long as Colibri serves it.

Wire Claude Code:

```bash
scripts/bootstrap-claude.sh
```

This copies the `/farm` skill into `~/.claude/skills/`, links
`claude-local-worker` into `~/.local/bin`, and registers Colibri's MCP server.
It reads the same `COLIBRI_BASE_URL` and `COLIBRI_API_KEY`, plus
`COLIBRI_MODEL` (default `qwen3.6-colibri`) and `COLIBRI_CONTEXT` (default
`131072`). See `docs/claude-code.md` for the details.

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
