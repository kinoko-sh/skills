# Properties, Checks, and Search Steering

A Kinoko workload is only as good as what it asserts and how it steers exploration. Read this when designing checks and `steer`/`better` resources, or when reviewing an existing `model.lua` that is not finding bugs.

## 1. Turn guarantees into concrete checks

Never settle for vague goals ("test failover", "test replication"). Inspect the SUT's code, docs, comments, and past bugs for **concrete claims** — conservation laws, state-machine invariants, durability of acknowledged writes, isolation guarantees, authorization boundaries, bounded memory/CPU — and encode each claim as a check.

### Choosing the right check type

| Check | When evaluated | Use for | Watch out for |
| --- | --- | --- | --- |
| `always(name, fn(r))` | Every tick where all resources `fn` touches have a reading | Safety invariants ("money is neither made nor lost", "an order is whole or absent", "enforced implies over limit"). | Accessing a resource with no reading aborts the call without failing that tick. Keep each `always` focused on only the resources it truly needs so an unrelated outage doesn't silence it. |
| `eventually(name, fn(r))` | Once faults end and the system settles (up to 20 virtual seconds) | Convergence / liveness ("pending queue drains to 0", "shadow matches primary", "grace expires"). | **A resource that cannot be read after settling is itself a finding.** Don't `down`-fault a service that needs >20s to recover, and guard dependent `eventually` checks cleanly (see `references/patterns.md`). |
| `sometimes(name, fn(r))` | Must hold at least once across the entire search | Reachability / sanity goals ("at least one failover completed", "rate limit triggered", "compaction ran"). | Unreached `sometimes` fails the run. Use these as compass checks to prove the workload actually reaches the interesting regions of your system. |
| `reply(action, name, fn(asked, answer))` | On every completed or timed-out action call | Per-request contracts ("unauthorized role is always rejected", "status is 200 or 409", "no 500s"). | Under faults, `answer` can be `nil` (no answer / timeout) or `{ err = ... }`. Allow expected transport/outage errors, and remember Postgres `sqlstate == "08006"` means **unknown whether committed**, not "rolled back". |

### Check naming rules

- **Every check name must be unique** across all `always`, `eventually`, `sometimes`, and `reply` declarations (duplicates are refused).
- **Check names are persistent identifiers** across runs (used for run-to-run diffs and history). Use clear, stable sentences and avoid renaming checks casually.

## 2. Steer the search (`steer` and `better`)

Kinoko uses Go-Explore-style exploration: it freezes guests when a `steer = true` resource hits a value not seen before, and forks new branches from those checkpoints.

### Rules for `steer = true`

1. **Each `steer` resource is its own independent search space.**
   If two values only matter *together* (for example, `level` and `x`, or per-product state across two products), combine them into **one** resource (e.g., a small table or formatted string). Otherwise, once `1` and `2` have each been seen separately, `(1, 2)` will not be treated as new.
2. **Bucket wide or continuous values.**
   Return coarse, meaningful states: `count // 20`, `memory_mb // 256`, or a compact phase enum (`"under"`, `"over"`, `"grace"`, `"enforced"`). Do not return raw tables or large payloads.
3. **Never put `steer = true` on noisy or monotonic values.**
   Clocks, timestamps, transaction IDs (`txid_current()`), and freshly generated UUIDs change constantly and waste search effort. Keep those out of `steer` resources.
4. **Separate steering from checking when helpful.**
   A detailed resource (`spine`, without `steer`) can feed your `always`/`eventually` checks while a tiny summary resource (`phase`, with `steer = true`) guides the search.

### Rules for `better = "more" | "less"`

A resource with `better = "more"` or `better = "less"` (returning a number) does **not** create its own buckets. Instead, when two guests land at the same `steer` state, Kinoko keeps the better one (for example: higher progress/fuel, lower memory or smaller backlog). Use `better` when an extra numeric dimension matters for reaching deeper states but putting it in `steer` would explode the state space.

## 3. Reviewing an existing workload

When asked to review a workload (or when a run passes too easily without finding anything), audit these five areas and report specific gaps rather than generic advice:

1. **Reachability (`sometimes`):** Are there `sometimes` checks proving key states and fault-recovery paths are actually reached? If not, a passing `always` may mean the workload never exercised the risky code path.
2. **Action & value diversity:** Do actions exercise boundary values (0, 1, exact limits, invalid/unauthorized inputs, deletes/cancellations, concurrent conflicts) rather than only happy-path defaults? Are `draw` slots ordered consistently so branch holds and subsetting work as intended?
3. **Fault coverage:** Are the right faults declared (`down`, `cut`, `slow`) for every stateful component and network edge? Are any `down` faults accidentally missing or targeting slow-boot containers that break settling?
4. **Steering quality:** Is at least one meaningful `steer = true` resource defined? Are coupled dimensions combined? Are noisy/high-cardinality values excluded or bucketed?
5. **Oracle soundness:** Do client-side durability checks avoid race-condition false positives (read ack log before querying SUT; record deletes before issuing delete; use `REPEATABLE READ` when comparing two SQL queries)?
