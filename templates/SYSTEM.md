# SYSTEM.md — the machine(s) this work runs on

*PI-owned and optional. Written by the PI (or by `/setup-lab` from the PI's answers);
agents read and obey it, never edit it. Lives at `lab/SYSTEM.md` for the lab default;
`/spawn-project` copies it into each project root, where you can tailor it. Delete any
section that doesn't apply — an absent section means "no constraint".*

## Hardware

<!-- What actually runs experiments: GPUs (model, count, VRAM), CPU/RAM, disk.
     The honest concurrency reality — e.g. "one 4090: ONE training run at a time;
     CPU-only evals can overlap." This is context for compute.max_concurrent_runs,
     not a replacement for it. -->

## Data locations

<!-- Where datasets, model caches, and scratch space live; what is read-only;
     what may be large-downloaded and where to put it (e.g. HF_HOME=D:\hf-cache).
     Anything that must NOT be re-downloaded or duplicated. -->

## Network & APIs

<!-- Proxies, firewalls, offline windows, rate-limited endpoints, which API keys
     exist as env vars (names only — never values). -->

## Scheduling rules

<!-- Shared-machine etiquette: quiet hours, "don't saturate the GPU while I'm
     working", queue/cluster usage (SLURM partition, sbatch wrapper) if any.
     If runs must go through a queue command, give the exact invocation. -->

## Forbidden actions

<!-- Hard no's beyond the lab protocol: paths never to write, services never to
     restart, "never use more than N GB of disk", "never install system packages". -->

## Quirks & footguns

<!-- The things you'd warn a new lab member about: flaky mounts, a driver that
     OOMs silently, antivirus slowing file IO, "long runs must set X". -->
