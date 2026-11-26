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
kinoko push [dir] [--system <system>] [--name <name>] [--keep] [--no-detect]
```

- Checks the workload, packs `images.tar` for `linux/amd64` (squashing multi-layer images), uploads only blobs not already stored, and prints `<workload-id>  <name>`.
- Default `--name` is the directory basename. Pass `--name` explicitly if pushing from `.` with an unhelpful folder name.
- `--system` groups the workloads of one codebase: `--system billing --name limiting` is addressed as `billing/limiting` by `kinoko run` and listed that way by `kinoko workloads`. Use it as soon as a repository has more than one workload.
- A push records the git branch, commit and (in GitHub Actions) the pull request it came from; `--pr`, `--title`, `--branch`, `--base`, `--commit` and `--pr-url` set them by hand, and `--no-detect` leaves them out (a push from a scratch checkout, or of someone else's branch).
- Pass `--keep` to reuse the existing `images.tar` when you only edited `model.lua` (saves rebuild/repack time).
- List pushed workloads with `kinoko workloads`.

## 3. Plan runs and respect the minute budget

### Billing and limits

- A run takes `1` to `240` minutes (`--minutes N`, default `10`), plus ~1 minute of boot/image-load overhead before search starts. The minutes are the search. After it, the fewest steps to each finding are worked out, and that is not bounded by `--minutes`: a 4-minute run with five findings stayed `running` for 24 minutes. `kinoko show` lists the findings as they come, so read them while it finishes, and do not take a long `running` for a hang.
- A run that ends as `error` with `no exit file` lost its machine (a spot machine taken back, usually). It cost nothing; start it again with `--seed` and the seed `kinoko show` prints.
- `kinoko push` can fail on the upload of `images.tar` with a `400` from storage. Run it again with `--keep`: the archive is already packed.
- `--keep` uploads the `images.tar` that is there, and `kinoko run --local` leaves one behind. Use it only to retry an upload. After a rebuild it pairs the new `model.lua` with the old images, and nothing says so: a check that reads a key the old driver does not send finds `nil` and passes. If a check that failed yesterday is quiet today, look at the readings in `kinoko show` for the key before believing it.
- A run that ends as `error` with `exit 137` ran its host out of memory. `kinoko show --log` prints `the host holds N GB` after each round, and it only grows. The findings of the run are lost with it. Run fewer minutes: a stack of eight containers (a service, its workers, Postgres, Temporal, two twins) filled 384 GB in eight minutes of search, and five-minute runs of it finish.
- The fewest steps are worked out for `always`, `reply` and `sometimes` findings. An `eventually` that did not hold comes with its last reading and no steps. Go back to it with a probe once the run has ended: `kinoko probe <run> <file>`, each line of the file `<node> end <command>`, the command run on the guest's host at the end of that line. `kinoko show <probe>` then prints every action and fault on the way to the node and what each command printed. Useful commands: `podman ps -a --format "{{.Names}} {{.Status}}"`, `podman logs --tail 30 <container>`, a `psql` on `pg_stat_activity` for who holds and who waits. A probe takes one of the account's run slots for about three minutes.
- Read a probe's log for `FAULT the end of ... did not work` before believing the finding. The harness could not end a fault (a `podman start` that exits 125 leaves the container down for the rest of the line), and the line is judged all the same. A slow or cut whose end fails because its container was down just then is harmless: the container comes back with a clean network.
- **Max 2 concurrent runs** per account.
- Minutes are reserved when a run starts (`N` for a run, `10` for a `probe`, `60` for a `session`), and unused minutes are refunded when the machine stops. Runs ending in `error` or `timeout` cost **0 minutes**.
- Always track your spend against the task's minute budget (from the user, or 30 minutes default in `SKILL.md`). Stop and report before exceeding it.

### Smoke first, then soak

1. **Smoke run (3–5 minutes):**
   ```sh
   kinoko run <workload> --minutes 4
   ```
   Confirms images load in the guest, setup finishes within `ready_deadline_s`, faults recover within the settle window (`settle_s`), and `sometimes` checks are reachable.
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

A finished run produces `report.txt`, `findings.jsonl` (one JSON record per finding with `check`, `kind`, `what`, `saw`, `times`, `node`, `tick`, `seed`), `shortest.jsonl` (minimized steps per finding), `findings.txt` (minimized steps with container logs), `map.json` (for each steered resource, the places it was read at and the actions between them), `probes.jsonl` (what probes printed), `log.txt`, and `tree.jsonl`. `kinoko show` formats the key sections directly; use the HTTP API (`GET /api/runs/{id}`) if you need raw signed URLs for `findings.jsonl` or `findings.txt`.
