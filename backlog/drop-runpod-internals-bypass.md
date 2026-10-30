# Backlog: return to `runpod.serverless.start()`

**Status**: Open — needs one live check on a GPU worker
**Opened**: 2026-10-30, with the MinerU 4.1 upgrade

## Why the bypass exists

`handler._bootstrap_main()` re-implements `runpod.serverless.worker.run_worker()`
from SDK internals (`rp_scale.JobScaler`, `rp_ping.Heartbeat`,
`rp_fitness.run_fitness_checks`) so the boot warmup and the serving loop share one
`asyncio.run()`. MinerU 3.x needed that: its vLLM `AsyncLLMEngine` was bound to
the loop that created it, so a warmup under its own loop left the serving loop
with a dead engine (`EngineDeadError` ~75 ms into the first request).

## What changed

MinerU 4 runs the engine on its own daemon thread with its own event loop
(`mineru.model.vlm.async_runtime.AsyncVlmPredictor`) and hands calls to it with
`call_soon_threadsafe`, so the engine no longer cares which loop the caller is
on. The bypass is no longer load-bearing; it stays in 2.0.0 because it is tested
and costs nothing.

## What dropping it buys

The worker stops depending on private SDK modules, and
`tests/test_runpod_internals.py` (the guard on their shape) can go.

## How to verify before dropping

1. Warm up with `asyncio.run(warmup_async())`, then call
   `runpod.serverless.start({...})` as the stock SDK does.
2. On a GPU worker: the first `standard` job after boot succeeds, and a FlashBoot
   restore (no `[mineru-warmup]` lines) still serves on the first request.
3. Concurrency (`MINERU_MAX_CONCURRENCY=2`) and SIGTERM draining behave as
   before.
