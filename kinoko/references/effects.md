# Effects

An effect is **inert data** returned from `update`; the host interprets it and
feeds the result back as a Msg through a defunctionalized callback. No closure
crosses that boundary — which is what makes traces replayable.

## Store

```yabu
Cmd.store.insert(%App.Row{text: "x"}, fn (id : Uuid) -> App.Msg.Saved(id) end)
Cmd.store.list(fn (rows : List<App.Row>) -> App.Msg.Loaded(rows) end)
Cmd.store.get(r.id, fn (row : Option<App.Row>) -> App.Msg.Got(row) end)
Cmd.store.update(r.id, %App.Row{r | text: "y"}, fn (id : Uuid) -> App.Msg.Saved(id) end)
Cmd.store.delete(r.id, fn (old : Option<App.Row>) -> App.Msg.Removed(old) end)
```

Which store a call targets is derived statically: from the **value's type** for
`insert`/`update`, and from the **callback's element type** for
`list`/`get`/`delete`. So the callback annotation is load-bearing — it is not
decoration.

**Identity is the store's.** A stored model declares `id : Uuid`; you omit it
when constructing and the store mints it on insert. Ids you pass to
`get`/`update`/`delete` come from rows you read back (`r.id`) — you never
fabricate one. A `Uuid` is type-distinct from `String`, so it cannot be
concatenated and a name cannot be passed where an id belongs.

## Transactions

All-or-nothing. Every op is validated before any write, so a rejected op leaves
the store untouched. One tx may mix models.

```yabu
Cmd.store.tx(
  [Tx.insert(%App.Row{n: 1}), Tx.update(r.id, %App.Row{r | n: 2}), Tx.delete(old)],
  fn (ids : List<Uuid>) -> App.Msg.Done(ids) end)
```

`Tx.delete` takes the **row**, not an id — the model comes from the value's type
exactly as `insert` does, and the id travels inside the row. One rule for all
three ops, and a transaction may still mix models.

**Replacing a set atomically** is the common case (re-analysing input, resyncing):
delete what is there and insert the new rows in ONE transaction, so a reader never
sees a half-empty store.

```yabu
Cmd.store.tx(
  List.concat(
    List.map(model.plan, fn (w : App.Word) -> Tx.delete(w) end),
    List.map(fresh, fn (w : App.WordInput) -> Tx.insert(%App.Word{text: w.text}) end)),
  fn (ids : List<Uuid>) -> App.Msg.Saved end)
```

Without this the mistake is appending: re-running an import silently doubles the
rows.

## AI

```yabu
Cmd.ai.generate("gpt-5.6-luna", prompt, fn (reply : String) -> App.Msg.Ready(reply) end)
```

The model is an argument, so the app chooses per call. Two things learned the
hard way:

- **Ask for JSON explicitly and completely.** Name every key and its type in the
  prompt ("each object MUST have all five keys: text (String), freq (integer),
  ..."), and say "no prose, only JSON".
- **Reasoning models spend their budget on reasoning.** With too small a token
  ceiling the reply comes back **empty**, and `JSON.parse` then fails with
  `invalid JSON: Unexpected end of JSON input`. If you see that, suspect the cap
  before the prompt.

## The AI → typed data pipeline

The full shape, with the failure path handled:

```yabu
# 1. a dedicated input model for what the AI supplies (the store owns id;
#    the app owns derived flags) — so the decode target is exactly the reply
defmodel App.WordInput do
  text : String
  freq : Int
  reading : String
end

# 2. fire, tracking that we are working
App.Msg.Analyze ->
  (%App.Model{model | error: "", status: "analyzing"},
   Cmd.ai.generate("gpt-5.6-luna", String.concat(instructions, model.transcript),
     fn (reply : String) -> App.Msg.Ready(reply) end))

# 3. decode, then persist — Err carries the reason, so surface it
App.Msg.Ready(reply) ->
  case JSON.parse(reply) do
    Result.Ok(inputs) ->
      (%App.Model{model | status: ""},
       Cmd.store.tx(
         List.map(inputs, fn (w : App.WordInput) ->
           Tx.insert(%App.Word{text: w.text, freq: w.freq, reading: w.reading, learned: false})
         end),
         fn (ids : List<Uuid>) -> App.Msg.Saved end))
    Result.Err(e) ->
      (%App.Model{model | error: e, status: ""}, Cmd.none())
  end
```

Always render `model.error` somewhere. A failed generation that vanishes silently
is the most common defect in an AI-backed app.

## JSON

`JSON.parse(s) : Result<T, String>` is **type-directed** — `T` comes from the
call site, and the runtime accepts a value only if it truly inhabits `T`
(rejecting a float for `Int`, a string for `Bool`, a missing field, a wrong
container). It cannot coerce, so a green `Ok` is a real guarantee.

The target must be statically known. Bind it to a typed field, a Msg payload, or
an annotation — an ambiguous target is a compile error, not a runtime surprise.

`JSON.stringify(v) : String` cleans as it goes: records drop their type tag,
`Option` becomes value-or-null, tuples become arrays. Use it to send model data
into a prompt.

## Blobs

Env-scoped object storage for text (up to 256KB per value); an empty key is
refused. Use it for content that is not a row: a pasted transcript, a rendered
artifact.

```yabu
Cmd.blob.put("transcripts/a", text, fn (key : String) -> App.Msg.Stored(key) end)
Cmd.blob.get("transcripts/a", fn (v : Option<String>) -> App.Msg.Got(v) end)
Cmd.blob.list("transcripts/", fn (keys : List<String>) -> App.Msg.Keys(keys) end)
Cmd.blob.delete("transcripts/a", fn (key : String) -> App.Msg.Dropped(key) end)
```

## Time, randomness, batching

```yabu
Cmd.time.now(fn (ms : Int) -> App.Msg.Stamped(ms) end)
Cmd.random.int(1, 6, fn (n : Int) -> App.Msg.Rolled(n) end)
Cmd.batch([cmdA, cmdB])
Cmd.none()
```

`random.int` is inclusive and refuses an empty range. Never reach for a host
clock or RNG directly — these exist so a run is reproducible under replay.
