---
name: kinoko
description: Use when building or changing software inside a Kinoko environment over MCP — writing Yabu (defmodel/deftype/def/defapp), staging patches, wiring Cmd effects (store, blob, ai.generate), or reading the environment graph. Covers the stage→reasons→restage loop, app composition, model evolution, and verification.
---

# Building in Kinoko

Kinoko is not a filesystem with a compiler. It is a **code database**: every
declaration is a content-addressed AST behind a versioned name index, and you
change it by staging a patch that either **promotes** (typechecks against
everything committed) or stays staged **carrying the reasons it cannot**.

That inverts the usual loop. You are not editing text and hoping; you get an
exact typecheck verdict on every attempt, so the fastest path is many small
staged patches, each read for its reasons.

## The loop

1. **Look before writing.** `symbols` (what exists), `search` (by name or
   source), `read` (full current source of decls), `deps` (what a symbol uses,
   and `usedBy` — the blast radius), `graph` (apps, stores, and the effect edges
   between them).
2. **Stage.** `stage_patch` with a patch id and Yabu source.
3. **Read the verdict.** `promoted: true` means it is live. `promoted: false` is
   **not success** — the patch is staged and inert. Read `reasons`, fix, restage
   the same patch id.
4. **Prove it.** `simulate` the app, `send` messages, `eval` a def,
   `store_query` the rows.
5. **Record the call.** `decide` when you chose between real alternatives;
   `decisions` to read what was already settled — honor those, or revise them on
   purpose.

Two rules that trip everyone:

- **A patch replaces the decls it names, whole.** There is no line editing.
  `read` the current source first if you are modifying, or you will silently
  drop fields and functions.
- **Symbols that change together belong in ONE patch.** A patch that breaks a
  committed dependent cannot promote — so if a Msg gains a variant, its `update`
  goes in the same patch.

## A patch is a commit, so name it like one

A promoted patch becomes a permanent step in the environment's history, and a
reviewer reads that history. So:

- **The patch id names ONE intent** — `reader-progress`, `story-word-count`. Not
  `fix`, `p2`, `tmp`. A stack of patches called `fix2` is unreviewable.
- **`message` says what it does**, for whoever reviews it later.
- **Iterating is restaging the SAME id.** A restage replaces your previous
  attempt, so the type errors you fixed along the way leave no trace — only the
  version that promoted becomes history. That is why you should stage a coherent
  intent and refine it, rather than staging a fresh id per attempt.

Because a patch only promotes when the whole committed image typechecks, every
step in that history is a working state. Keeping ids meaningful is what makes
that property useful to a human.

## Shapes

A `defapp` is one TEA loop: `init() -> (Model, Cmd<Msg>)`,
`update(msg, model) -> (Model, Cmd<Msg>)`, `view(model) -> Html`.

```yabu
defmodel Counter.Model do count : Int end
deftype Counter.Msg do Increment | Add(Int) end
def Counter.init() : (Counter.Model, Cmd<Counter.Msg>) do
  (%Counter.Model{count: 0}, Cmd.none())
end
def Counter.update(msg : Counter.Msg, model : Counter.Model) : (Counter.Model, Cmd<Counter.Msg>) do
  case msg do
    Counter.Msg.Increment -> (%Counter.Model{model | count: model.count + 1}, Cmd.none())
    Counter.Msg.Add(n) -> (%Counter.Model{model | count: model.count + n}, Cmd.none())
  end
end
def Counter.view(model : Counter.Model) : Html do
  <div><button on-click={Counter.Msg.Increment}>{String.from_int(model.count)}</button></div>
end
defapp Counter
```

## The five rules that cause the most rework

1. **Compose from several focused apps over shared stores — not one app with an
   internal router.** Apps are the composition primitive; the environment routes
   them and stores are the shared substrate. A `Dashboard`, a `Reader` and a
   `Review` over the same `Word`/`Story` stores is native. A monolith with
   `case model.screen` re-implements app switching *inside* an app and forces
   ephemeral nav state into a persisted Model.

2. **Every Model field must be defaultable**: `Int`, `String`, `Bool`, `Uuid`,
   `List`, `Map`, `Option`, tuple, or a nested model of those. **A custom
   `deftype` can never be a Model field** — so there is no `Screen` enum; express
   state with `String`, `Option<Uuid>`, `Bool`.

   **A model you store declares `id : Uuid`, and you never write it.** Identity
   belongs to the store: it mints the id on insert and projects it on every read,
   so record construction **omits** `id` and every row you read back carries a
   real one.

   ```yabu
   defmodel App.Word do
     id : Uuid          # declared, store-owned
     text : String
   end

   Cmd.store.insert(%App.Word{text: "猫"}, fn (id : Uuid) -> App.Msg.Saved(id) end)
   ```

3. **Persist durable nouns in stores, not in the Model.** The Model is session
   state. Anything that must survive a reload goes through `Cmd.store.*`.

4. **A committed model field can never change type or be removed.** Add new
   fields (defaultable); leave superseded ones vestigial. Attempting removal
   fails with `frozen-removal`.

5. **`always(...)` must hold for every reachable state**, including the one
   `init` produces. Put invariants in `update`; `simulate` will find the message
   sequence that breaks them.

## Effects

Effects are inert data the host interprets; callbacks are defunctionalized, so
**no closure crosses the boundary**. The complete set:

`Cmd.none` `Cmd.batch` · `Cmd.store.insert/list/get/update/delete/tx` ·
`Cmd.time.now` `Cmd.random.int` · `Cmd.blob.put/get/list/delete` ·
`Cmd.ai.generate(model, prompt, cb)`

`ai.generate` takes the model **per call** — the app decides. Pair it with
type-directed JSON to get typed data out of prose:

```yabu
Cmd.ai.generate("gpt-5.6-luna", prompt, fn (reply : String) -> App.Msg.Ready(reply) end)

App.Msg.Ready(reply) ->
  case JSON.parse(reply) do            # target type is inferred from the arm
    Result.Ok(rows) -> (model, Cmd.store.tx(List.map(rows, fn (r : App.Input) -> Tx.insert(...) end), cb))
    Result.Err(e) -> (%App.Model{model | error: e}, Cmd.none())
  end
```

`JSON.parse` returns `Result<T, String>` and returns `Ok` **only** for a value
that truly inhabits `T` — it cannot be coerced. The target must be statically
known (bind it to a typed field, a Msg payload, or an annotation).

## Stdlib (all of it)

`List.map/filter/append/concat/length/is_empty` ·
`String.length/concat/from_int` · `JSON.parse/stringify` · `Option.Some/None` ·
`Result.Ok/Err` · `Tx.insert/Tx.update/Tx.delete`

That is the whole list. There is no `List.head` and no `List.contains` — if you
need one, work around it (e.g. `List.filter` + `List.length`) rather than
assuming it exists, and say so rather than inventing a function.

## Working without being handed ids

`workspace` lists every project and environment you can reach — start there
rather than asking for an id. `create_env` makes an empty one; `delete_env`
removes one that holds nothing (it refuses anything with declarations, rows or
staged patches, so it tidies your own failed attempts and cannot destroy work).

## Proposing a change for review

When a change deserves a human's eyes before it lands in a shared environment:

1. `fork_env` the target — the fork is an exact copy (identical content
   addresses), so you start from a known state.
2. Work in the fork, one intent per patch, each with a message.
3. `open_pr` from the fork to the target with a title and a body.
4. `review_pr` shows what a reviewer will see: which nodes changed, and — the part
   that matters — which **capabilities** the proposal adds or removes, such as an
   app gaining the power to delete from a store.

You cannot merge. A human approves in the console. That is deliberate: propose
clearly, and make the capability changes easy to see rather than easy to miss.

## References

Load these when the task calls for them:

- `references/patterns.md` — multi-app composition, cross-app navigation,
  screens without an enum, list/detail, forms.
- `references/effects.md` — every effect with a worked call, the AI+JSON
  pipeline, transactions, blobs.
- `references/evolution.md` — changing a live model safely, what the gate
  rejects and why, tombstones.
- `references/verification.md` — `always`/`sometimes`, `deftest`, `simulate`,
  and how to prove a change before trusting it.
