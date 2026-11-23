# Triaging and Time-Travel Debugging Findings

A `found` outcome is a **candidate**, not a confirmed SUT bug. Always verify whether the failure is a real bug in the system under test, a bug in `model.lua`, or a workload/settling issue before reporting or patching.

## 1. Read the finding and minimized steps

Start with:

```sh
kinoko show <run-id>
```

Extract from the output:
- Which check failed (`FAIL ...`) and what reading it saw (`saw`).
- The finding's node (`first at node <N>`) and virtual timestamp (`<T> s` after setup).
- The `== the fewest steps to each ==` section (from `shortest.jsonl`): exact actions, faults, unanswered requests, readings, and the `BROKEN` event in virtual seconds.

If the run ended in `error` or `timeout`, run `kinoko show <run-id> --log` and inspect the failure step and tail of the log first.

## 2. Classify before diving deep

Check the common non-SUT causes first:

- **Model / oracle bug:**
  - Client-side durability file read *after* querying the SUT (races with concurrent writes) or delete recorded *after* issuing the delete.
  - Treating Postgres `sqlstate 08006` or HTTP `nil`/`err` as "not committed" when the write actually succeeded before the disconnect.
  - Comparing two queries taken at different moments instead of one `REPEATABLE READ` transaction.
  - Lua error / instruction or memory limit exceeded (`check` is null in `findings.jsonl`).
- **Workload / settling bug:**
  - `eventually` failed because a resource was still unreadable after the 20s settle window (for example, a slow-booting container was given a `down` fault).
  - Container crashed due to missing env var, bad compose config, or guest OOM.
- **Real SUT bug:**
  - The minimized timeline shows a clean, valid sequence of actions/faults that violates a genuine system guarantee.

Never guess between these — inspect the real guest state at the failing moment.

## 3. Time-travel debugging on ended runs

Kinoko replays the exact path to any node deterministically and executes commands on an isolated copy of the guest at any virtual second after setup (without perturbing the rest of the timeline). Commands run on the **guest's host**, so target containers with `podman logs`, `podman ps -a`, `podman exec <container> ...`, etc.

### Option A: Batch probes (`kinoko probe`) — best first tool

Use `kinoko probe` when you want logs and state snapshots at one or more timestamps in a single shot. A probe reserves 10 minutes, runs all lines in one job (each line on its own isolated guest copy at that tick), and terminates automatically when done.

Write a probe file (`probes.txt`), one `<node> <seconds|end> <command>` per line:

```text
778 21.0 podman ps -a --format '{{.Names}} {{.Status}}'
778 22.5 podman logs --tail 50 app
778 22.5 podman exec postgres psql -U postgres -c 'select * from accounts'
778 end  podman exec client cat /tmp/acked
```

Launch and read it:

```sh
kinoko probe <run-id> probes.txt     # prints <probe-run-id>
kinoko show <probe-run-id>           # once complete, report holds each command's output
```

Batch as many questions as you can into one probe file — all lines for a node share one replay pass, and multiple nodes run in parallel. Put dependent commands on one line with `;` since separate lines run on independent copies.

### Option B: Interactive session (`kinoko session` + `kinoko ask`)

Use a session when you need iterative, hypothesis-driven forensics along one finding's timeline (typically its minimized path):

```sh
kinoko session <run-id> <node>                 # prints <session-id>; ready in a few minutes
kinoko ask <session-id> 22.5 podman logs app   # waits until ready, runs on isolated copy at 22.5s
kinoko ask <session-id> 22.6 podman exec postgres psql -U postgres -c 'select * from accounts'
```

- Each `ask` runs on its own throwaway copy of the guest at that virtual second, so mutating commands inside `ask` are safe.
- **Always cancel the session as soon as you finish:**
  ```sh
  kinoko cancel <session-id>
  ```
  Sessions reserve 60 minutes, stay up for 15 minutes of idle time (up to 60 minutes max), and bill minutes while alive.

## 4. Cross-reference and report

1. Match the timeline (`shortest.jsonl`), container logs, and probed state against the SUT's source code to establish the exact mechanism.
2. Separate **observed evidence** (run ID, seed, node, virtual timestamps, exact log lines and command outputs) from **root-cause explanation**.
3. If you fix the bug (or fix `model.lua`):
   - Re-run `kinoko check` and `kinoko run --local`.
   - Push (`kinoko push`) and re-run with the failing run's `--seed` first, then run a fresh unseeded check to verify the fix holds generally.
