# Hardware

## Reference box

| Part | Value |
|---|---|
| CPU | Intel Core i7-3770K, 4C/8T, AVX only |
| RAM | 32 GB DDR3 |
| GPU | NVIDIA GeForce GTX 1070, 8 GB, Pascal |
| Storage | Samsung 850 EVO 250 GB, SATA |
| OS | Debian 13 |
| Driver | NVIDIA 570.211.01 |

## Why it works

The GTX 1070 runs the dense chain and about 2,800 experts. The remaining
experts sit in a 17 GB host pool in RAM. Colibri reads them over PCIe, so the
CPU and DDR3 feed the pool rather than doing all the math.

The CPU has no AVX2, so the engine is built with `ARCH=native` and uses its
SSE/scalar fallback. CPU-only inference is about 0.27 tok/s; Vulkan is about
21 tok/s at 128K context.

## Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| RAM | 16 GB | 32 GB |
| GPU | Vulkan 1.2, 6 GB | Vulkan, 8 GB+ |
| Disk | 25 GB free | SSD, 30 GB free |
| OS | Linux | Debian/Ubuntu |

## Upgrades

- A BC-250 (16 GB GDDR6, ~357 GB/s) runs the same model at roughly 60 tok/s.
- A 12-16 GB GPU (RTX 3060 12 GB, RTX 2000 Ada 16 GB) raises the resident
  expert count and lets you use a larger quant.
- More RAM raises the host pool, which lowers PCIe traffic.
