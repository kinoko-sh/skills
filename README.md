# Kinoko Skills

Agent skill for deterministic simulation testing with [Kinoko](https://kinoko.sh).

Teaches a coding agent how to design `compose.yaml` + `model.lua` workloads, define invariants and search-steering resources, validate locally, run cloud explorations within a minute budget, and time-travel debug findings.

## Prerequisites

- **Kinoko CLI:**
  ```sh
  curl -fsSL https://kinoko.sh/install.sh | sh
  kinoko login
  ```
  (Or set `KINOKO_API_KEY` from [kinoko.sh](https://kinoko.sh) Settings. Set `KINOKO_URL` if targeting a self-hosted or dev instance.)
- **Docker or Podman** with Compose (used by `kinoko push` to pack `images.tar` and by `kinoko run --local`).

## Install

### `npx skills` (recommended — works with Claude Code, Codex, Cursor, etc.)

```sh
npx skills add kinoko-sh/skills
```

To update later: `npx skills update`.

### Claude Code plugin

```sh
claude plugin marketplace add kinoko-sh/skills
claude plugin install kinoko@kinoko-skills
```

### Manual

```sh
git clone --depth 1 https://github.com/kinoko-sh/skills /tmp/kinoko-skills
cp -R /tmp/kinoko-skills/kinoko ~/.claude/skills/
```

(Or copy into `.claude/skills/` for a single project.)

## Usage

Invoke the skill directly with `/kinoko` (or `$kinoko` depending on your agent), or just describe a Kinoko task in natural language.

### Starter prompts

End-to-end:
```
/kinoko Build a Kinoko workload for this service, verify it locally, run a 5-minute smoke test and a 15-minute run, and root-cause anything that fails.
```

Focused tasks:
```
/kinoko workload Design a compose.yaml and model.lua for the billing service in src/billing/ and get `kinoko run --local` passing.
```
```
/kinoko properties Review our model.lua checks and steering resources — what invariants or failure modes are we missing?
```
```
/kinoko run Push the workload in ./kinoko and run a 10-minute exploration.
```
```
/kinoko debug Triage run <run-id> and root-cause the failing check.
```

## What's inside

| File | Purpose |
| --- | --- |
| `kinoko/SKILL.md` | Entry point: prerequisites, doc grounding, minute-budget rules, module router |
| `kinoko/references/workload.md` | Designing `compose.yaml` + `model.lua`, Lua sandbox rules, local validation loop |
| `kinoko/references/properties.md` | Writing `always`/`eventually`/`sometimes`/`reply` checks, `steer`/`better` guidance, reviewing models |
| `kinoko/references/run.md` | `kinoko push`, smoke vs. soak runs, minute budgets, interpreting run outcomes |
| `kinoko/references/debug.md` | Triaging findings vs. model bugs, `kinoko probe`, `kinoko session` + `kinoko ask` |
| `kinoko/references/patterns.md` | Worked idioms and real-world pitfalls (ack tracking, repeatable-read checks, slow startups, faults) |

## Tools invoked

The skill uses `kinoko`, `docker` or `podman` (via `kinoko push` and `kinoko run --local`), and optionally `curl` to fetch live docs from `https://kinoko.sh/docs.md`.

## Validation

```sh
python3 scripts/validate-skills.py
```

## License

[MIT](LICENSE)
