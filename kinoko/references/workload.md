# Building a Kinoko Workload

A Kinoko workload is a directory containing `compose.yaml` and `model.lua` (plus any local build contexts). You can scaffold a minimal example with `kinoko init [dir]` or a buggy bank tutorial with `kinoko onboarding [dir]`.

Read `references/properties.md` when designing checks and steering resources, and `references/patterns.md` for worked idioms and common pitfalls.

## 1. Design the minimal topology (`compose.yaml`)

Keep the topology as small as possible — every extra container adds memory overhead and widens the state space.

### Hard requirements

- **Target platform:** x86_64 Linux (`linux/amd64`) running under Podman with **no internet access**.
- **`pull_policy: never`** on every service. `kinoko push` builds `build:` services, pulls other images for `linux/amd64`, squashes each to a single layer, and packs them into `images.tar`.
- **Images must be named by tag, never by digest alone** (`image: foo@sha256:...` is refused).
- **Explicit `container_name:`** on every service referenced by `model.lua` (setup, mechanisms, or faults). `kinoko check` rejects any mismatch.
- **Dedicated idle `client` container** for running `setup`, actions, and resources:
  - `entrypoint: ["sleep", "infinity"]`
  - `volumes: ["/hook:/hook:ro"]` (mounts Kinoko's mechanism binaries from the guest host)
  - Carries only the lightweight CLI tools your model needs (`psql`, `wget`/`curl`, `jq`, etc.)
  - **Never targeted by a `down` fault** (mechanism containers cannot be taken down, except for `usage`).
- **Keep images small.** The guest's disk lives in 8 GB of RAM using Podman's `vfs` storage driver. `kinoko push` squashes layers automatically, but `vfs` still holds one unpacked copy per container. Prefer `-alpine` or minimal distroless/static images; aim for `images.tar` of a few hundred MB, well under 1 GB.

## 2. Write `model.lua`

`model.lua` is executed once at load time to collect declarations, then **re-executed from line 1 before every function call**. Functions are effectively pure: globals or locals mutated inside a callback are discarded before the next call.

### Declarations

```lua
timing { ready_deadline_s = 120, tick_ms = 5 }   -- optional; these are the defaults
setup("name", "container", "command")             -- run once in order; nil runs on guest host

resource("name", {
  <mechanism>,                                    -- see Mechanisms table
  <request fields>,
  read = function(res) return ... end,            -- optional transform -> JSON value
  steer = true,                                   -- optional: search explores new values
  -- or: better = "more" | "less"                 -- optional: keep best exemplar per bucket
})

action("name", { <mechanism> }, function(draw, r)
  return { ... }                                  -- mechanism request, or nil to skip
end)

always("unique name", function(r) return ... end)
eventually("unique name", function(r) return ... end)
sometimes("unique name", function(r) return ... end)
reply("action_name", "unique name", function(asked, answer) return ... end)

fault { down = "container" }
fault { cut = { "container_a", "container_b" } }
fault { slow = "container_a", to = "container_b", ms = 200 }  -- `to` is optional
```

### Mechanisms

Each mechanism runs as a persistent process inside a container via `/hook/`, speaking line-delimited JSON (`{"result": ...}` or `{"err": ...}`). Every container running a mechanism must mount `/hook:/hook:ro`.

| Mechanism | Request fields | Result fields | Notes |
| --- | --- | --- | --- |
| `http = { container, host, port }` | `path`, optional `method`, `headers`, `body` | `status`, `headers`, `body`, `json` (nil if non-JSON) | Persistent HTTP client; `body` may be a string or Lua table (serialized as JSON). |
| `postgres = container` | `query` | Array of row objects keyed by column name; `err` has `sqlstate` and `message` | Connects via `PGHOST`/`PGUSER`/`PGPASSWORD`/etc. env vars. Name duplicate columns with `AS`. |
| `bash = container` | `command` | `code`, `stdout`, `stderr` | Up to 32 concurrent shells per action; 10s virtual timeout. Persist shared state in files, not shell vars/cwd. |
| `usage = container` | *(none)* | `memory_mb`, `cpu` (centicores over last 1s, e.g. 250 = 2.5 cores) | Container still needs `/hook:/hook:ro`. Has no reading while container is down. |
| `stdin = { container, command }` | Any JSON object | Any JSON `result` or `err` | Custom long-running helper speaking one JSON line in / one JSON line out. |

`http`, `bash`, and `usage` enforce strict field access: reading a nonexistent field (like `out.output` instead of `out.stdout`) is an error caught by `kinoko check`.

### Action draws and readings

- `draw.pick(list)` selects one element; `draw.int(low, high)` selects an integer in `[low, high]`.
- Each branch has a deterministic **temperament** (pace, hold duration, action/value subsetting). Because a branch holds onto drawn choices, keep the *n*-th draw of an action consistent in meaning across calls (do not conditionally skip earlier draws so that draw #2 sometimes picks an account and sometimes picks an amount).
- `r` inside an `action` holds the **last known reading** of each resource (seeded from setup), so actions can still construct requests while a service or database is down.
- Returning `nil` from an action skips doing anything on that tick.

### Sandbox and size limits

To preserve byte-for-byte deterministic replay, `model.lua` runs in a restricted Lua sandbox:

- **Forbidden:** `os`, `io`, `debug`, `package`, `require`, `pcall`, `load`, metatables, clocks, `math.random`, non-deterministic `math` (`sin`, `exp`, `log`). `pairs`/`next` iterate in deterministic key order.
- **Budget per call:** 1M instructions to load the script, 2M instructions per callback, 56 MB memory, capped pattern-matching cost (`^`-anchored or plain `string.find(..., 1, true)` is much cheaper than multiple `*`/`+`/`-` quantifiers), `string.rep` capped at 1 MB.
- **Line & step caps:**
  - Single mechanism request or response: **16 KB** max (larger answers become an `err`).
  - `setup` command + container name: **4082 bytes** max (put longer scripts in the container image).
  - Each `setup` step times out after **30 seconds**; split slow readiness waits into multiple steps (see `references/patterns.md`).

## 3. Fast local loop (free, no cloud minutes)

Always iterate locally until clean before pushing to the cloud:

```sh
kinoko check [dir]
kinoko run --local [dir]
```

- `kinoko check` validates `model.lua` syntax, sandbox rules, mechanism result fields, unique check names, and `compose.yaml` container names and image tags in milliseconds.
- `kinoko run --local` packs `images.tar` (pass `--keep` if only `model.lua` changed and images did not), boots the workload on local Docker, runs `setup`, executes one fault-free line of actions, settles, and evaluates checks.
  - Confirms containers boot cleanly, every resource produces readings, actions get answered, and no `always`/`eventually`/`reply` check breaks on the happy path.
  - Note: `sometimes` checks report "not reached" locally rather than failing.
  - Fix every startup, reading, or check error locally before spending cloud minutes.

## Self-review before pushing

- Every service has `pull_policy: never`, a tagged image (no `@sha256:`), and `container_name:` matching `model.lua`.
- Every container hosting a mechanism mounts `/hook:/hook:ro`, and no mechanism container (except `usage`) has a `down` fault.
- `setup` waits explicitly for all services to be ready and seeded before search starts.
- Every `action` keeps its `draw` order consistent and handles transient outage errors gracefully in its `reply` check.
- `kinoko check` and `kinoko run --local` both pass.
