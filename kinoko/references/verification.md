# Proving a change

A patch that promotes is type-correct. That is not the same as correct. These are
the tools for the rest, cheapest first.

## Invariants in the code

`always(cond)` asserts a property of every state `update` produces. It runs on
every real transaction AND is the thing `simulate` hunts for counterexamples
against.

```yabu
def App.update(msg : App.Msg, model : App.Model) : (App.Model, Cmd<App.Msg>) do
  always(model.weekly != "")
  always(List.length(model.plan) >= 0)
  case msg do ...
end
```

It must hold for **every reachable state, including the one `init` produces** — an
`always` that only holds after the first user action will fail immediately.

`sometimes(cond)` is the opposite: a reachability goal. It does not fail when
false; `simulate` reports whether the walk ever reached it. Use it to prove an
interesting state is actually attainable ("the plan is non-empty", "a story
exists"), which is how you catch a feature that is unreachable through the UI.

## Simulation

`simulate` drives a seeded random walk over the app's messages with effects
included, and reports:

- `failures` — the `always` violations it found, with the message sequence.
- `reached` — which `sometimes` goals were hit.
- `skippedVariants` — Msg variants it could not synthesize arguments for (often
  the ones carrying loaded rows). Those are NOT covered; drive them with `send`.
- `finalModel` — where the walk ended up.

Zero failures over 200 steps is a real signal about crashes and invariants. It is
not a signal about the variants it skipped, and not about anything the AI returns
(simulation stubs effects deterministically).

## deftest

For a specific scenario with a known answer, a `deftest` is a committed test that
runs with the suite rather than a one-off.

## Driving the live app

`send` dispatches a real message and returns the new model — the only way to
exercise a path simulation skipped, and the way to confirm an effect actually
worked end to end:

```
send { app: "App", msg: {"$v": "App.Msg.Analyze", "a": []} }
```

Then `store_query` the model to see whether rows really landed, and `eval` a def
to check a pure computation. Together these answer "did it work", which
`promoted: true` never does.

## What to check before calling a feature done

1. It promotes.
2. `simulate` shows no failures, and the `sometimes` goals you care about are
   reached.
3. The messages simulation skipped were driven with `send`.
4. The durable data is really in the store (`store_query`), not just in a Model
   that a reload would erase.
5. Failure paths render: an AI/JSON error is visible in the view, not swallowed.

## A note on the environment graph

`graph` is derived from the typed code, not from what happened to run — so it is
the honest answer to "what can this app touch". Read it after a change: an app
that gained an unexpected write edge, or an AI call you did not intend, shows up
there. It is also the fastest way to see whether your composition came out as
intended (one monolith versus several focused apps over shared stores).
