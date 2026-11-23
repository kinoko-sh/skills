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

## 4. Slow-starting services (>30s setup or >20s recovery)

- Each `setup` step has a **30-second timeout**. For a service that needs several minutes to boot and migrate, raise `ready_deadline_s` and split the wait into bounded steps ending with an explicit assertion:
  ```lua
  timing { ready_deadline_s = 600 }
  for step = 1, 12 do
    setup("service starts " .. step, "client", "timeout 25 sh -c 'until [ -e /tmp/serving ]; do sleep 0.5; done'; true")
  end
  setup("service is ready", "client", "test -e /tmp/serving")
  ```
- Settling allows at most **20 virtual seconds**. Do **not** declare `fault { down = "svc" }` for a container that takes >20s to restart — every run where it is killed late will fail to settle. Fault its network (`cut`, `slow`) and kill faster-restarting dependencies (`db`, `redis`, workers) instead.

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

- **Guest disk is 8 GB RAM (`vfs`):** Five containers sharing a 500 MB image consume 2.5 GB of guest RAM before the workload even starts. Keep images lean.
- **`bash` concurrency:** Up to 32 shells stay open per `bash` action. Never rely on `cd` or shell variables persisting across calls; write state to files in `/tmp`, and avoid clobbering a shared temp file from concurrent invocations.
- **Fault interactions:**
  - Killing and restarting a container (`down`) resets any active `cut` or `slow` rules on it (the restarted container gets a new IP).
  - Two `slow` faults on the same source container do not stack (`tc qdisc add` on the second is ignored, and whichever ends first removes the qdisc).
  - A `cut` or `slow` started while the peer container is down cannot resolve the peer's IP and is skipped harmlessly.
- **Large inline scripts:** `setup` commands (plus container name) cap at 4082 bytes, and all resource requests combined share the same limit. Put complex helper scripts or observers into the container image (or a small HTTP observer running inside `client`) rather than huge inline commands.
- **Avoiding `eventually` false positives from in-flight work:** Expose an explicit `busy` / in-flight count resource if an async operation can still be completing, assert `eventually("all requests finished", ...)` on it, and guard dependent `eventually` checks when `r.busy > 0`.
