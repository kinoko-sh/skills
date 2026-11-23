# Pushing and Running on Kinoko

Read this when pushing a workload, planning cloud runs, tracking minute spend, or reading run outcomes.

## 1. Pre-flight

Never push an unverified workload:

```sh
kinoko check [dir]
kinoko run --local [dir]
```

Fix any local failure before spending cloud minutes.

## 2. Push the workload

```sh
kinoko push [dir] [--name <name>] [--keep]
```

- Checks the workload, packs `images.tar` for `linux/amd64` (squashing multi-layer images), uploads only blobs not already stored, and prints `<workload-id>  <name>`.
- Default `--name` is the directory basename. Pass `--name` explicitly if pushing from `.` with an unhelpful folder name.
- Pass `--keep` to reuse the existing `images.tar` when you only edited `model.lua` (saves rebuild/repack time).
- List pushed workloads with `kinoko workloads`.

## 3. Plan runs and respect the minute budget

### Billing and limits

- A run takes `1` to `240` minutes (`--minutes N`, default `10`), plus ~1 minute of boot/image-load overhead before search starts.
- **Max 2 concurrent runs** per account.
- Minutes are reserved when a run starts (`N` for a run, `10` for a `probe`, `60` for a `session`), and unused minutes are refunded when the machine stops. Runs ending in `error` or `timeout` cost **0 minutes**.
- Always track your spend against the task's minute budget (from the user, or 30 minutes default in `SKILL.md`). Stop and report before exceeding it.

### Smoke first, then soak

1. **Smoke run (3–5 minutes):**
   ```sh
   kinoko run <workload> --minutes 4
   ```
   Confirms images load inside the guest's 8 GB RAM disk, setup finishes within `ready_deadline_s`, faults recover within the 20s settle window, and `sometimes` checks are reachable.
2. **Main / soak run (10–30+ minutes):**
   Only launch a longer run once the smoke run finishes cleanly (or after fixing workload/model issues it surfaced).
   ```sh
   kinoko run <workload> --minutes 15
   ```
3. **Deterministic re-run / fix verification:**
   Pass `--seed <seed>` from an earlier failing run to check whether the same search seed still reproduces after a fix, then follow up with a fresh unseeded run.

## 4. Monitor and read results

```sh
kinoko runs                    # list runs, newest first, with status
kinoko show <run-id>           # summary, findings, minimized steps, report
kinoko show <run-id> --log     # include full machine/harness log
kinoko cancel <run-id>         # stop a running job or session immediately
```

### Interpreting outcomes

| Outcome | Meaning | Next step |
| --- | --- | --- |
| `running` | Still booting, searching, or minimizing findings | Wait and re-check `kinoko show <run-id>` (avoid tight polling; check every 30–60s). |
| `pass` | No check failed (and all `sometimes` checks were reached) | Report coverage/stats from `report.txt`. If you expected a bug, review `references/properties.md` to tighten checks or steering. |
| `found` | At least one check failed | Hand off to `references/debug.md` to verify and root-cause. |
| `error` | Run could not complete (`detail` + tail of `log.txt` shown) | If `detail` is `no exit file`, a spot machine was reclaimed (cost: 0 min) — simply re-run with the same `--seed`. Otherwise inspect `--log` (common causes: OOM from oversized images, setup timeout, container crash at boot). |
| `timeout` | Machine exceeded its run + grace window (cost: 0 min) | Inspect `--log`; often caused by stuck setup or excessive settling. |
| `cancelled` | Manually stopped | Charged only for minutes the machine was up. |

### Run artifacts

A finished run produces `report.txt`, `findings.jsonl` (one JSON record per finding with `check`, `kind`, `what`, `saw`, `times`, `node`, `tick`, `seed`), `shortest.jsonl` (minimized steps per finding), `findings.txt` (minimized steps with container logs), `log.txt`, and `tree.jsonl`. `kinoko show` formats the key sections directly; use the HTTP API (`GET /api/runs/{id}`) if you need raw signed URLs for `findings.jsonl` or `findings.txt`.
