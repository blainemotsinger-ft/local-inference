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
