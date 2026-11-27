# Properties, Checks, and Search Steering

A Kinoko workload is only as good as what it asserts and how it steers exploration. Read this when designing checks and `steer`/`better` resources, or when reviewing an existing `model.lua` that is not finding bugs.

## 1. Turn guarantees into concrete checks

Never settle for vague goals ("test failover", "test replication"). Inspect the SUT's code, docs, comments, and past bugs for **concrete claims** — conservation laws, state-machine invariants, durability of acknowledged writes, isolation guarantees, authorization boundaries, bounded memory/CPU — and encode each claim as a check.

### Choosing the right check type

| Check | When evaluated | Use for | Watch out for |
| --- | --- | --- | --- |
| `always(name, fn(r))` | Every tick where all resources `fn` touches have a reading | Safety invariants ("money is neither made nor lost", "an order is whole or absent", "enforced implies over limit"). | Accessing a resource with no reading aborts the call without failing that tick. Keep each `always` focused on only the resources it truly needs so an unrelated outage doesn't silence it. |
| `eventually(name, fn(r))` | Once faults have ended and every action was answered, within `settle_s` virtual seconds of calm (default **2**) | Convergence / liveness ("pending queue drains to 0", "shadow matches primary", "grace expires"). | **A resource that cannot be read after settling is itself a finding.** Don't `down`-fault a service that needs >20s to recover, and guard dependent `eventually` checks cleanly (see `references/patterns.md`). |
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

## How long "eventually" is

A settling run stops injecting, waits for in-flight actions, and then judges. It ends **as soon as every `eventually` holds**; otherwise it gives them `settle_s` seconds of calm (default 2, `config { settle_s = N }`) and reports the ones that still do not hold. The whole settle is capped at `max(20, settle_s + 12)` virtual seconds, which is also how long it waits for an action that never answers or a resource that cannot be read.

So the question for every `eventually` is: what is the slowest legitimate way this becomes true after the last fault, and is `settle_s` longer than that?

- A retry loop, a sweep, a lease expiry, a restart: add their periods up. Two seconds covers almost none of them.
- A larger `settle_s` is cheap on healthy lines (the settle ends when the checks hold) and only costs time where something is slow or stuck, which is what you want to hear about.
- If the system's recovery clock is minutes (a cron sweep, a five-minute timer), a run that waits for it explores little. Shorten the clock in the workload instead: an environment variable if the SUT has one, a settings override, or a build step that rewrites the constant in the image and fails when the line it expects is gone. Say in the workload what was shortened and to what, and ask for the constant to become a setting.
- A check that cannot be judged after settling (its resource is unreadable) is a finding too.

## One `eventually` per stage

A single "everything completes in the end" check finds the first reason something does not complete, and then nothing else: the shortest way to it is the reason already known, and every other reason hides behind it until that one is fixed. For a pipeline with stages, write an `eventually` for each stage that can get stuck in a way worth naming (admitted, verified, released), and let the general one skip what an earlier check already reports:

```lua
eventually("billing verifies every finalization of its own", function(r) ... end)
eventually("every invoice billing took is processed", function(r)
  return every(r, function(i)
    if i.unverified or i.behind_an_unverified_one then return true end  -- reported above
    return i.processed
  end)
end)
```

The same goes for an `always` that a known defect breaks on most runs: give the defect its own check and keep it out of the broader one, with a comment that says which check has it. A check nobody expects to pass teaches nothing, and one that is always red stops being read.

