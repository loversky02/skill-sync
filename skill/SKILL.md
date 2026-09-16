---
name: skill-sync
description: "Report and reconcile skill drift between Claude's user-skill directory and Codex's, without shadowing plugin-provided skills. Use when skills exist on one agent but not the other, when a skill was edited on one side only, after installing or updating skills, or when asked to mirror, compare, audit, or sync skills across Claude and Codex."
user-invocable: true
when_to_use: "Invoke when skills must be compared or mirrored between Claude and Codex, or when a skill appears to exist on one agent but not the other."
category: utilities
keywords: [skills, sync, drift, codex, claude, mirror, audit, plugin]
argument-hint: "[report|sync] [--to claude|codex] [--apply] [--force] [--prune] [--json]"
license: MIT
metadata:
  author: loversky02
  version: "1.2.0"
  repository: https://github.com/loversky02/skill-sync
---

# skill-sync

Compare `~/.claude/skills/` with `~/.codex/skills/` and copy what is missing or
stale. Read-only unless `--apply` is passed; deletes only under `--prune`.

## Run it

```sh
skill-sync report                   # what differs
skill-sync report --json            # machine-readable
skill-sync sync --to codex          # plan only, no writes
skill-sync sync --to codex --apply  # perform the copies
```

`--force` additionally overwrites skills whose contents differ; it only writes
when combined with `--apply`.

`--prune` deletes files inside the skills being written that the source no
longer has. Reach for it after renaming or removing a file in a skill, since a
plain sync leaves the old one at the destination forever. It only deletes with
`--apply`, and a dry-run lists every path it would remove.

If the `skill-sync` wrapper is not on `PATH`:

```sh
python3 ~/.claude/tools/skill-sync/skill_sync.py report
```

## Reading the report

| Bucket | Meaning | Action |
|---|---|---|
| `in_sync` | present both sides, trees hash identically | nothing to do |
| `only_in_claude` | Claude user skill absent from Codex | `sync --to codex` |
| `only_in_codex` | absent from Claude **and** from every plugin | `sync --to claude` |
| `plugin_provided` | in Codex, and served to Claude by a plugin | never sync |
| `content_differs` | both sides have it, contents diverge | inspect, then `--force` |

## The mistake this exists to prevent

Claude serves skills from two places: `~/.claude/skills/` and each plugin's
`skills/` directory under `~/.claude/plugins/cache/`. Skills such as
`code-review`, `grilling`, and `tdd` reach Claude through a plugin.

A naive two-directory comparison reports those as missing from Claude and copies
duplicates into `~/.claude/skills/`, where they shadow the managed plugin copy
and then rot as the plugin updates. `plugin_provided` is a separate bucket for
exactly this reason and is never a sync candidate in either direction.

## What counts as drift

SHA-256 of every file in the skill directory, with each file's relative path
folded into the digest. An edit inside `references/`, `agents/`, or `scripts/`,
and a renamed support file, all register. Hashing `SKILL.md` alone would miss
them. `__pycache__`, `.git`, `.DS_Store`, and compiled Python are excluded as
build noise, and are skipped when copying too.

## Safety

- No write happens without `--apply`.
- Overwriting a `content_differs` skill needs `--apply --force` together.
- `--apply` rescans both trees immediately before its first write and aborts,
  copying nothing, if the plan no longer matches what is on disk.
- Deletion happens only under `--prune`, and only inside a skill this run is
  writing. A skill the destination has and the source does not is never a prune
  candidate — otherwise one pruned sync would wipe every Codex-only skill.
  Build artefacts at the destination are left alone.

## Source

Repository: https://github.com/loversky02/skill-sync — `README.md` there covers
flags, path overrides, and the test suite.
