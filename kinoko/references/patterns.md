# Kinoko Patterns and Pitfalls

Proven patterns adapted from real Kinoko workloads, plus the operational gotchas that most often cause broken runs or false positives.

## 1. Standard HTTP + Postgres workload (`compose.yaml` + `model.lua`)

```yaml
services:
  postgres:
    image: postgres:17-alpine
    pull_policy: never
    container_name: postgres
    environment:
      POSTGRES_PASSWORD: pg

  app:
    build: app
    image: my-app:local
    pull_policy: never
    container_name: app
    environment: &pg
      PGHOST: postgres
      PGUSER: postgres
      PGPASSWORD: pg
    depends_on: [postgres]

  client:
    image: postgres:17-alpine
    pull_policy: never
    container_name: client
    environment: *pg
    entrypoint: ["sleep", "infinity"]
    volumes:
      - /hook:/hook:ro
    depends_on: [app]
```

```lua
setup("postgres up", "client", "until pg_isready -q; do sleep 0.2; done")
setup("schema", "client", [[psql -qc "create table accounts (name text primary key, balance int not null); insert into accounts values ('alice', 100), ('bob', 100), ('carol', 100)"]])
setup("app up", "client", "until wget -qO- http://app:8080/health; do sleep 0.2; done")

resource("total", {
  postgres = "client",
  query = "select sum(balance) from accounts",
  read = function(rows) return rows[1].sum end,
  steer = true,
})

resource("accounts", {
  postgres = "client",
  query = "select name from accounts order by name",
  read = function(rows)
    local names = {}
    for i, row in ipairs(rows) do names[i] = row.name end
    return names
  end,
})

local amounts = { 1, 5, 20, 50 }
action("transfer", { http = { "client", "app", 8080 } }, function(draw, r)
  local from, others = draw.pick(r.accounts), {}
  for _, name in ipairs(r.accounts) do
    if name ~= from then others[#others + 1] = name end
  end
  return { method = "POST", path = "/transfer?from=" .. from .. "&to=" .. draw.pick(others) .. "&amount=" .. draw.pick(amounts) }
end)

always("money is conserved", function(r) return r.total == 300 end)
reply("transfer", "transfer succeeds or refuses cleanly", function(asked, answer)
  return answer == nil or answer.err ~= nil or answer.result.status == 200 or answer.result.status == 409
end)

fault { down = "app" }
fault { down = "postgres" }
fault { cut = { "app", "postgres" } }
fault { slow = "app", to = "postgres", ms = 200 }
```

## 2. Tracking acknowledged writes without race false positives

When checking durability ("nothing acknowledged is lost"), concurrent actions and resource reads can race unless you order file reads and writes carefully:

- **Insert/publish:** append the ID to `/tmp/acked` *after* the system acknowledges it; in the check resource, read `/tmp/acked` **before** querying the system.
- **Delete/cancel:** append the ID to `/tmp/gone` **before** sending the delete; in the check resource, read `/tmp/gone` **after** querying the system.

```lua
-- Read acked BEFORE querying DB, and read gone AFTER querying DB:
resource("lost", {
  bash = "client",
  command = [[said=$(sort -u /tmp/acked 2>/dev/null); have=$(psql -qAtc "select id from orders") && comm -23 <(echo "$said") <(echo "$have" | sort) | comm -23 - <(sort -u /tmp/gone 2>/dev/null) | grep -c . || true]],
  read = function(out) return tonumber(out.stdout) end,
})
```

If `psql` fails while Postgres is down, the `&&` short-circuits and prints nothing, so `tonumber(out.stdout)` returns `nil` (no reading on that tick, avoiding a false positive during an outage).

## 3. Atomic multi-query checks

Never compare two separate SQL queries run back-to-back in an `always` check — concurrent writes can land between them. Wrap them in a single `REPEATABLE READ` transaction (as in a table-scan vs. index-scan check):

```lua
resource("index_mismatch", {
  bash = "client",
  command = [[psql -qAt 2>/dev/null <<'SQL'
begin isolation level repeatable read;
set local enable_indexscan = off; set local enable_indexonlyscan = off; set local enable_bitmapscan = off;
select count(*) from items where order_id > 0;
set local enable_indexscan = on; set local enable_indexonlyscan = on; set local enable_bitmapscan = on; set local enable_seqscan = off;
select count(*) from items where order_id > 0;
commit;
SQL]],
  read = function(out)
    local found = {}
    for count in out.stdout:gmatch("%d+") do found[#found + 1] = tonumber(count) end
    if #found == 2 then return found[1] - found[2] end
  end,
})
```

## 4. Slow-starting services (>30s setup, or recovery slower than the settle)

- Each `setup` step has a **30-second timeout**. For a service that needs several minutes to boot and migrate, raise `ready_deadline_s` and split the wait into bounded steps ending with an explicit assertion:
  ```lua
  config { ready_deadline_s = 600 }
  for step = 1, 12 do
    setup("service starts " .. step, "client", "timeout 25 sh -c 'until [ -e /tmp/serving ]; do sleep 0.5; done'; true")
  end
  setup("service is ready", "client", "test -e /tmp/serving")
  ```
- An `eventually` gets `settle_s` seconds of calm (default **2**), and a settle is capped at `max(20, settle_s + 12)` virtual seconds. A container that takes longer than that to come back from `fault { down = "svc" }` fails every run where it is killed late. Either raise `settle_s` to cover its restart, or leave `down` to what restarts fast (`db`, `redis`, workers) and use `pause`, `cut` and `slow` on the slow starter: `pause` stops a process for a while without a restart.

## 5. Checking memory and CPU with `usage`

Mount `/hook:/hook:ro` on the service container to sample its cgroup `memory_mb` and `cpu` (centicores over the last second):

```lua
resource("app_memory", {
  usage = "app",
  read = function(u) return u.memory_mb end,
})
resource("app_memory_bucket", {
  usage = "app",
  read = function(u) return u.memory_mb // 128 end,
  steer = true,
})
always("app stays under 1 GB", function(r) return r.app_memory < 1024 end)
```

## 6. Operational pitfalls to remember

- **Image size:** `images.tar` may be up to 5 GB and containers of one image share its layers (`overlay`), but every push uploads it and every run loads it. Keep images lean, and give different trees different image names: two workloads that both build `app:latest` overwrite each other locally.
- **One local run at a time:** `kinoko run --local` uses the compose file's fixed container names, so a second local run (or a leftover `docker compose up` of another workload with a `db` or `web`) collides. On arm64 hosts the images are still `linux/amd64`: build steps run under emulation and can take many times longer, so bake slow one-off work (migrations, asset builds) into an image layer.
- **`bash` concurrency:** Up to 32 shells stay open per `bash` action. Never rely on `cd` or shell variables persisting across calls; write state to files in `/tmp`, and avoid clobbering a shared temp file from concurrent invocations.
- **Fault interactions:**
  - Killing and restarting a container (`down`) resets any active `cut` or `slow` rules on it (the restarted container gets a new IP).
  - Two `slow` faults on the same source container do not stack (`tc qdisc add` on the second is ignored, and whichever ends first removes the qdisc).
  - A `cut` or `slow` started while the peer container is down cannot resolve the peer's IP and is skipped harmlessly.
- **Large inline scripts:** `setup` commands (plus container name) cap at 4082 bytes, and all resource requests combined share the same limit. Put complex helper scripts or observers into the container image (or a small HTTP observer running inside `client`) rather than huge inline commands.
- **Avoiding `eventually` false positives from in-flight work:** Expose an explicit `busy` / in-flight count resource if an async operation can still be completing, assert `eventually("all requests finished", ...)` on it, and guard dependent `eventually` checks when `r.busy > 0`.

## 7. Twins of third-party services

When the SUT's correctness depends on a provider you cannot run in the guest (a payment API, a tax engine), you write a twin. A twin is also where a model goes wrong quietly, so:

- **Do not derive the twin from the SUT.** A twin that implements what the SUT's own verifier expects can only agree with it. Write the twin from the provider's documentation, then write a small conformance script that asks the same questions of the provider's sandbox and of the twin, and commit the provider's answers. Run the twin against them whenever it changes. (Doing this for a Stripe twin showed that the system under test expected two balance transactions where Stripe writes one.)
- **Say what was not checked.** List in the twin's header which behaviours come from the sandbox, which from documentation only, and which are guesses. A finding that rests on a guess is a question for the provider first.
- **Let the twin tell callers apart** (an API key per caller is enough) and keep a record of every write: who, with which idempotency key, in what order. The checks then compare what the SUT believes with what the provider was actually asked.
- **Fail loudly on what the twin does not model.** Count unknown routes and its own exceptions, expose them as a resource, and assert `always` that there are none: a finding caused by the twin must not look like one caused by the SUT.
- **Keep a twin with in-memory state out of `down` faults.** `cut`, `slow` and `pause` it instead, or give it a file to come back to.
- **Compress the provider's clocks in the twin** (retry schedules, an hour before auto-finalization) by the same order as the SUT's, and say so.

## 8. An oracle that reads two systems

A check that compares the SUT's database with a twin's record reads them at two moments. Make the order part of the design:

- For "the provider saw X, so the SUT must already have saved Y" (intent before effect), read the provider first and the SUT second.
- For "the SUT claims Y, so X must be true at the provider", read the SUT first and the provider second.
- An observer that needs both reads the provider, then the SUT, then the provider again, and uses the first reading for the first kind of check and the last for the second.
- Where the SUT cannot close a window (the provider has no compare-and-set, so an input can change between the SUT's last read and its write), do not let it fail an `always`. Have the twin record whether the input changed after the SUT last read it, exclude that case from the `always`, and add a `sometimes` named as a known gap so the run still says whether the window was reached.
- One HTTP observer in `client` that returns a compact row per entity keeps this in code you can test, and keeps the answer under the 16 KB limit. Leave out keys that are null or false (Lua reads a missing key as neither), and bound how many entities a run creates. Bound it in the driver, with a refusal: a `when` alone is overshot, because the actions already under way were drawn while there was still room.
- A driver that watches the system in a thread of its own has to outlive the system. One uncaught error while the database is down ends the thread, every reading after it is the last one it took, and an `eventually` then fails on a reading from the middle of a fault. Catch everything once per round, and say in the reading how old it is (`waiting: 31` seconds for an answer) so that a stale one cannot pass for the system's.
- `down` kills a container the way a power cut does: its peers get no FIN. A database then keeps the dead client's session, with its row locks and its place among `max_connections`, until its own keepalive gives up, which for Postgres is two hours by default. A few kills later every writer waits on a lock nobody holds, or the database answers `too many clients already`, and each reads as a finding about the system. Decide what the workload is about. To test the system and not the database's defaults, start the database with the timeouts production has, scaled like the other timers (`postgres -c tcp_keepalives_idle=2 -c tcp_keepalives_interval=1 -c tcp_keepalives_count=3`), and say in the README what production's settings decide.
- A driver that reads the system's database beside it needs its own short timeouts. A `down` fault can kill the database with a query in flight and no goodbye, and libpq then waits for TCP keepalive, two hours by default. The driver's call never returns and the report says the system never answered. For libpq: `connect_timeout`, `keepalives_idle`, `keepalives_interval`, `keepalives_count`, `tcp_user_timeout`.
- Have the observer say why, not only what. An `eventually` that fails is reported with its last reading alone, so a row that says `stuck` is a dead end and one that says `attempted, no result, draft deleted` is a diagnosis. The same flags let the model give each known way of getting stuck a check of its own.
- A `reply` check sees an answer only if it comes while the harness still waits for it. For an effect that stays (a row changed, a plan moved), read it from a resource and write an `always`: a slow first call is then not a missed finding.
- Two resources are read at different instants. An `eventually` that compares them can fail on the last sample because one moved in between. When two things must agree, have the driver read both in one request and hand them back together, or leave out the pair when two readings around the call differ.
- Keep answers small enough to read in a report. `kinoko show` cuts a long reading short, and what is cut is usually the part after the change. Send what changed (`moved: {inbox: [null, "free"]}`), not the state before and after.
- When the driver caps how many calls are under way, count how many it refuses. On a local line most actions of a burst can come back refused, and a check that needs an answer then judges almost nothing.
- A twin that sends webhooks must go on sending for as long as the provider does, in the twin's compressed time. One that gives up after a minute turns a fault that outlasts its retries into an event the system never hears of, which reads as a liveness bug of the system. Cap the wait between tries below `settle_s`, so that the try after the last fault comes while the run still watches.

