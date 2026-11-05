# Benchmarks

Measured on the reference box in `hardware.md`. One machine, one driver, one
build. Treat these as a starting point, not a guarantee.

## Qwen3.6-35B-A3B

| Context | Backend | Model on | Decode | Warm start |
|---|---|---|---|---|
| 64K | CPU only | HDD | 0.27 tok/s | 374 s |
| 64K | Vulkan, GTX 1070 | HDD | 22.4 tok/s | 374 s |
| 128K | Vulkan, GTX 1070 | HDD | 21.0 tok/s | 400 s |
| 128K | Vulkan, GTX 1070 | SATA SSD | 21.7 tok/s | 39 s |

Decode figures are a 256-token coding answer measured end to end, prompt
included.

## Laptop: RTX 2000 Ada, 8 GB

A laptop with an Intel Core Ultra 9 185H, 64 GB of RAM, and an NVIDIA RTX 2000
Ada laptop GPU with 8 GB, Vulkan, model on an NVMe SSD. Colibri picked the
context itself. Speeds are Colibri's own per-turn figures from `/profile`:
tokens generated over the turn's wall time, prompt included.

Chat: the same eight questions in one conversation, up to about 1,300 tokens.
"Turns 2-8" leaves out the first turn, which pays for loading.

| Model | GPU weight cache | Context | First turn | Turns 2-8 |
|---|---|---|---|---|
| Qwen3.6-35B-A3B | Colibri's default, 4.39 GiB | 64K | 14.9 s | 25.6 tok/s |
| Qwen3.6-35B-A3B | 2.5 GiB (`--gpu-cache 2.5`) | 64K | 15.9 s | 18.8 tok/s |
| Qwen3-Coder-30B-A3B | 2.5 GiB (`--gpu-cache 2.5`) | 32K | 21.7 s | 12.1 tok/s |

`/farm` worker: add braces to variables and `[[ ]]` to tests, 43 shellcheck
warnings in 4 scripts, then run shellcheck twice and the test suite.

| Model | GPU weight cache | Result |
|---|---|---|
| Qwen3.6-35B-A3B | Colibri's default | Two runs; both slowed to a crawl after Colibri took GPU memory back from the weights, at about 13,000 and 15,000 tokens. No result. |
| Qwen3.6-35B-A3B | 2.5 GiB (`--gpu-cache 2.5`) | Finished in 5 min 59 s, 28 turns, 14 edits, every check passing. Largest request 16,324 tokens; no memory taken from the weights. |
| Qwen3-Coder-30B-A3B | 2.5 GiB (`--gpu-cache 2.5`) | 4 steps and no edits in 10 minutes, then slowed to a crawl at about 11,000 tokens with the card full (7.6 of 8.2 GB). |

See "GPU memory" in the README for what the cache setting does.

## Expert tier

At 128K, the engine reported:

- 2,798 experts resident on the GTX 1070 (4.6 GB of a 4.7 GB budget)
- 10,240 experts in a 17 GB host pool in RAM
- 0 disk loads and 0 CPU-RAM misses during the turn
- 67.8% speculative-draft acceptance on a long coding answer

## Commands

```bash
# Start detached
coli start --background --no-browser

# Check
coli status

# Stop
coli stop
```

A direct request:

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen3.6-colibri","messages":[{"role":"user","content":"Say hello in one word."}],"max_tokens":8,"temperature":0}'
```
