# Kinoko skill

Teaches an agent how to build software inside a [Kinoko](https://kinoko.sh)
environment: the Yabu language, the stage → reasons → restage loop, model
evolution, effects, and how to prove a change before trusting it.

**You may not need this.** Connecting to Kinoko's MCP server already delivers a
short orientation with the connection, and the same reference material is
available on demand as `kinoko://guide/*` resources. Install this when you want
the depth in your local context — for example when working in Claude Code — or
when your client does not surface MCP instructions.

## Install

Into a single project:

```sh
git clone --depth 1 https://github.com/kinoko-sh/skills /tmp/kinoko-skills
cp -R /tmp/kinoko-skills/kinoko .claude/skills/
```

Or for every project, copy it into `~/.claude/skills/` instead.

## What is in it

| file | what it covers |
| --- | --- |
| `SKILL.md` | the loop, the shapes, and the rules that cause the most rework |
| `references/patterns.md` | composing several apps over shared stores, navigation, list/detail |
| `references/effects.md` | every effect worked through, plus the AI → typed JSON pipeline |
| `references/evolution.md` | changing a live model without breaking stored rows |
| `references/verification.md` | `always`/`sometimes`, simulation, and what "done" means |

## Where this comes from

Generated from the Kinoko source, which holds the single copy of this text — the
same files the MCP server serves as `kinoko://guide/*`. Do not edit here: this
directory is regenerated on every release, so a change made in place is lost, and
until it is, it teaches a language that differs from the one the server runs.
