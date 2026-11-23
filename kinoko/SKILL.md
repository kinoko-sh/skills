---
name: kinoko
description: >
  Entry point for deterministic simulation testing with Kinoko (kinoko.sh).
  Use when designing or updating a Kinoko workload (compose.yaml and model.lua),
  writing or reviewing checks and steering resources, running local checks or
  cloud explorations, or triaging and time-travel debugging run findings.
argument-hint: "[workload|properties|run|debug] <prompt>"
---

# Kinoko

Kinoko runs a containerized workload (`compose.yaml` + `model.lua`) inside a deterministic x86_64 Linux hypervisor, explores its state space by branching frozen guests while injecting faults (`down`, `cut`, `slow`), and reports failing checks with minimized reproduction steps and time-travel debugging (`probe` and `session`/`ask`).

## Before starting

1. Check that `kinoko` is installed (`command -v kinoko`). If missing, tell the user to install it with `curl -fsSL https://kinoko.sh/install.sh | sh`.
2. For any cloud command (`push`, `run` without `--local`, `runs`, `show`, `probe`, `session`, `ask`, `cancel`), confirm auth works (`kinoko workloads`). If not signed in, ask the user to run `kinoko login` or set `KINOKO_API_KEY`. (`init`, `onboarding`, `check`, and `run --local` do not require auth.)
3. Treat `https://kinoko.sh/docs.md` (CLI + `model.lua` reference) and `https://kinoko.sh/openapi.json` as the canonical live reference if you are ever unsure about a flag, field, or API route.

## Modules

Load only the reference file(s) needed for the current step. Do not read all of them up front.

| Argument | Reference | Use when |
| --- | --- | --- |
| `workload` | `references/workload.md` | Designing, scaffolding, or updating `compose.yaml` and `model.lua`, or getting `kinoko check` and `kinoko run --local` green. |
| `properties` | `references/properties.md` | Turning system guarantees into `always`/`eventually`/`sometimes`/`reply` checks, choosing `steer`/`better` resources, or reviewing an existing model. |
| `run` | `references/run.md` | Pushing a workload, planning smoke/soak runs within a minute budget, and reading `kinoko show` output. |
| `debug` | `references/debug.md` | Triaging a `found` or `error` run, separating real SUT bugs from model bugs, and running `kinoko probe` or `kinoko session`/`ask`. |
| *(patterns)* | `references/patterns.md` | Worked `compose.yaml` / `model.lua` idioms and operational pitfalls — read when implementing or troubleshooting a workload. |

## Free-form prompts and workflows

If the prompt does not name a single module, derive the shortest chain from what exists in the repo to the user's goal. Common shapes:

- **Test a new system:** `references/workload.md` + `references/properties.md` (+ `references/patterns.md`) -> local validation -> `references/run.md` (short smoke run, then soak) -> `references/debug.md` if anything fails.
- **Investigate a failure:** `references/debug.md` -> fix SUT or model -> `references/run.md` to verify (re-run with the same `--seed` first, then a fresh seed).
- **Review / improve an existing workload:** `references/properties.md` + `references/patterns.md`.

## Scoping and minute budget

Cloud runs, probes, and sessions spend metered minutes. Before starting a multi-step or cloud workflow, ask the user once in a single message for anything not already specified:

- **Scope:** which service, feature, or guarantees to focus on.
- **Minute budget:** total cloud minutes you may spend across runs, probes, and sessions. If the user does not set one, default to **30 minutes** total (for example: a 3–5 min smoke run, a 15–20 min main run, plus headroom for probes/re-runs).
- **Code edits:** whether you may edit SUT code (or only workload files).

Once scoped, work autonomously within the budget until the goal is reached or you hit a genuine blocker. Always validate locally (`kinoko check` and `kinoko run --local`) before spending cloud minutes, and always cancel interactive sessions (`kinoko cancel <session>`) as soon as you finish debugging.

If your context is compacted mid-task, re-read this file and whichever `references/*.md` files apply to your current step before continuing.
