# Changing a live model

Models are persisted columnar data with **forward compatibility as a hard rule**,
not a convention. Rows written before a change must stay readable after it, and
nothing rewrites old rows — migration is lazy by design. That gives three
constraints the gate enforces before a patch can promote.

## The three rules

1. **A committed field can never change type.** `frozen-type-change`. The old
   rows still hold the old type; reinterpreting those bytes is data corruption.

2. **A committed field can never be removed.** `frozen-removal`. Its tag stays
   burned so a later field cannot reuse it.

3. **A newly added field must be defaultable.** `non-defaultable`. Old rows have
   no value for it, so it must have a computable zero: `Int` (0), `String` (""),
   `Bool` (false), `Uuid` (the nil uuid), `List` ([]), `Map` ({}), `Option`
   (None), a tuple of those, or a nested model whose every field is defaultable.

**A custom `deftype` is NOT defaultable.** A variant type has no zero, so it can
never be a model field. This is the constraint people hit first — see
`patterns.md` for expressing modes without an enum.

## So how do you change a model?

Add, don't replace. When a field is superseded, leave it in place — vestigial —
and add the new one:

```yabu
defmodel App.Model do
  words : List<String>     # superseded, kept because it is committed
  plan : List<App.Word>    # the real field now
  status : String          # new; String is defaultable, so old rows read fine
end
```

This looks untidy and is correct. A model accumulates history; that is the price
of never breaking a persisted row. If the dead weight becomes genuinely
confusing, that is a conversation about a data migration, not something to sneak
past the gate.

## Reading the gate's verdict

The reasons are precise. `promoted: false` with
`frozen-removal: field "App.Model foo" cannot be removed` means exactly that: you
dropped a field while rewriting the decl. Almost always the fix is that you
`read` the current source, edited from an older memory of it, and lost fields —
so re-`read` and merge.

## Renaming

There is no rename. A new name is a new field (and a new symbol). To move a
value, add the new field, write both for a while if you must, and leave the old
one. For a *symbol* (a `def`), a rename is a new decl plus a tombstone on the old
one — and every caller must move in the SAME patch, since a patch that orphans a
committed dependent cannot promote.

## The id field is not yours

A stored model declares `id : Uuid` and the **store owns it**: it mints the id on
insert and projects it on every read. So construction omits `id`, and the frozen
rules above still apply to it like any other field — which is precisely why it is
a `Uuid` and not an `Int`. Identity is stable across environments, so forking or
copying an environment cannot collide two rows, and nothing can guess the next id.

## Stores versus session state

`defmodel` declares a shape. It becomes a **store** when code persists it
(`Cmd.store.*`); an app's own `Model` is session state that happens to also be a
declared model. Keep durable nouns in stores: an app whose state lives only in
its Model loses everything on reload, which is the single most common way a
generated app looks like a toy.

## Tombstones

A patch may carry `tombstones` — names to retire. Use them to remove a `def` that
nothing references. You cannot tombstone your way out of the model rules above:
a committed model field stays.
