# Patterns

## A product is several apps over shared stores

The instinct from SPA work is one app with a client-side router. It is the wrong
shape here and it costs real rework, so it is worth stating plainly.

Apps ARE the composition primitive. The environment serves each at
`/app/<env>/<App>`, and every app in an environment shares the same stores. So a
learning product is not one `JapaneseStories` with `case model.screen`; it is:

```
Dashboard   writes Word, writes Story, calls AI     (the workbench)
Reader      reads Story, reads Word                 (focused reading)
Review      reads Word, writes Word                 (study loop)
```

Each app is a small TEA loop with almost no branching. The graph then shows the
system honestly: which app can touch what, and which is read-only (provably — it
has no write edge).

**Why the monolith actively hurts:** navigation state (`screen`, `reading`,
`reviewing`) has to live in the Model, but Model fields must be defaultable, so
you cannot use a clean `Screen` enum and end up with stringly-typed nav in
persisted state. Splitting deletes that problem rather than working around it.

## Cross-app navigation

A relative single-segment `href` resolves to a sibling app in the same env:

```yabu
<a href="Reader">Read your stories</a>       # from /app/<env>/Dashboard
```

Standalone this is a normal navigation. Embedded in the console graph, the app
page reports the intent to the console, which **moves the camera to that app's
node** instead of loading another app inside a card. The graph shows these as
`nav` edges, derived from the anchors in your views — so the map tells you where
a user can go, not just where data flows.

## Screens without an enum

When you genuinely need modes inside one app, express them with defaultable
types and keep the branching in one place:

```yabu
defmodel App.Model do
  # ... durable-ish session fields
  open : Option<Uuid>    # a detail view: Some(id) is "open on this row"
  editing : Bool
  status : String        # "" | "saving" | "analyzing" — also drives loading UI
end

def App.view(model : App.Model) : Html do
  <div>
    {case model.open do
      Option.Some(id) -> App.detail(model, id)
      Option.None -> App.list(model)
    end}
  </div>
end
```

`status : String` doubles as the loading flag — set it when you fire the effect,
clear it in the handler, and branch on it in the view so a long call shows a
spinner instead of a dead button.

## List / detail over a store

The detail view filters the already-loaded rows rather than issuing a `get`:
fewer effects, and the list stays the single source of truth.

```yabu
def App.detail(model : App.Model, id : Uuid) : Html do
  <div>
    <button on-click={App.Msg.Close}>Back</button>
    {List.map(List.filter(model.rows, fn (r : App.Row) -> r.id == id end), fn (r : App.Row) ->
      <article><p>{r.text}</p></article>
    end)}
  </div>
end
```

## Per-item handlers

An event attribute takes a fully-applied Msg, so binding an id per row works:

```yabu
<button on-click={App.Msg.MarkDone(r.id)}>Got it</button>   # applied: carries the id
<input on-change={App.Msg.SetName} />                       # a constructor ref: gets the value
```

`on-click` wants a Msg **value**; `on-change` wants the **constructor**, which is
applied to the input's value for you.

## Loading rows on boot, then chaining

`init` fires one read; each arrival can trigger the next. This is the idiomatic
way to hydrate several stores.

```yabu
def App.init() : (App.Model, Cmd<App.Msg>) do
  (%App.Model{...}, Cmd.store.list(fn (rows : List<App.Word>) -> App.Msg.WordsLoaded(rows) end))
end

App.Msg.WordsLoaded(rows) ->
  (%App.Model{model | words: rows},
   Cmd.store.list(fn (ss : List<App.Story>) -> App.Msg.StoriesLoaded(ss) end))
```

The model a read targets is inferred from the **callback's element type** — that
is how `store.list` knows which store to read.

## Styling

Views are JSX over an allowlist, styled with Tailwind utility classes. No
`<script>`, no `on*` attributes, no `javascript:` URLs — the renderer rejects
them. Write real design (spacing, hierarchy, states), not a bare prototype.
