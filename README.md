# skill-sync

`skill-sync` reports drift between Claude user skills and Codex skills, then can
copy missing or stale skill directories in either direction. It is read-only by
default; it writes only under `--apply` and deletes only under `--prune`.

Claude plugin skills are discovered separately below each plugin version's
`skills/` directory, including plugins that group skills into category
directories. A skill available to Claude from a plugin is reported as
`plugin_provided`; it is never copied into Claude's user-skill directory.

## Requirements

- Python 3.13
- Standard library only for the CLI
- pytest for running the test suite

## Commands

With the wrapper on `PATH` (see Install), run from any directory:

```sh
skill-sync report
skill-sync report --json
skill-sync sync --to codex
skill-sync sync --to claude
skill-sync sync --to codex --apply
skill-sync sync --to codex --apply --force
skill-sync sync --to codex --apply --force --prune
```

Equivalent without the wrapper:

```sh
python3 skill/skill_sync.py report
```

`report` prints five buckets:

- `in_sync`: both user-skill directories contain the name and their `SKILL.md`
  byte hashes match.
- `only_in_claude`: present only in Claude's user-skill directory.
- `only_in_codex`: present only in Codex and not supplied by a Claude plugin.
- `plugin_provided`: present in Codex and available to Claude from a plugin.
- `content_differs`: present in both user-skill directories with different
  `SKILL.md` hashes.

`sync --to codex` plans copies from `only_in_claude`. `sync --to claude` plans
copies from `only_in_codex`. Both commands copy the whole skill directory.
Plugin-provided skills are informational and are never sync candidates.

## Flags

- `report --json`: emit the five report buckets as JSON arrays.
- `sync --to {claude,codex}`: required sync destination.
- `sync --apply`: perform the planned copies. Without this flag, sync only
  prints its plan and makes no filesystem changes.
- `sync --force`: include `content_differs` skills in the overwrite plan. An
  overwrite occurs only when `--force` and `--apply` are both present.
- `sync --prune`: delete destination files inside the skills being written that
  the source no longer has. A deletion occurs only when `--prune` and `--apply`
  are both present; see Pruning below.
- `--claude-dir PATH`: override Claude's user-skill directory. Default:
  `~/.claude/skills`.
- `--codex-dir PATH`: override the Codex skill directory. Default:
  `~/.codex/skills`.
- `--plugins-dir PATH`: override Claude's plugin cache. Default:
  `~/.claude/plugins/cache`.
- `-h`, `--help`: show command or subcommand help.

Path override flags belong after `report` or `sync`. A missing plugin-cache
directory is treated as an empty cache. Missing, invalid, or unreadable Claude
or Codex skill directories produce a clean error and a nonzero exit status.

Directory entries whose names begin with `_`, non-directories, and directories
without a `SKILL.md` file are ignored.

## Pruning

Sync is additive by default: rename or delete a file in a skill and the old one
survives at the destination indefinitely, because nothing ever removes it.
`--prune` closes that gap, deliberately narrowly.

It considers only the skills this run is writing, and only their contents:

```text
prune (2):
  skill-sync/STALE.md
  skill-sync/plans
```

A dry-run prints that list and deletes nothing, so the removals are reviewable
before they happen. Only the topmost path of a stale subtree is listed, since
removing a directory takes its children with it.

What `--prune` will never do:

- delete a skill the destination has and the source does not. Those are not in
  the write plan, so a pruned `sync --to codex` cannot touch a Codex-only skill
  and cannot touch a plugin-provided one.
- delete build artefacts (`.git`, `__pycache__`, `.DS_Store`, compiled Python).
  They are absent from the source by design, so treating them as stale would
  make pruning quietly destructive to a symlinked git checkout.
- delete anything without `--apply`.

## Stale-plan guard

`sync --apply` rescans both directories immediately before its first write and
compares the result against the plan it printed. If anything changed in the
meantime — a skill added, removed, or edited by another process — it copies
nothing and exits nonzero:

```text
skill-sync: error: skill directories changed while the plan was being prepared;
nothing was copied - re-run to see the current plan
```

This closes the window between reading and writing within a single `--apply`
run. It does not detect a change that happens after that final rescan, and it
says nothing about drift between a separate earlier `report` and a later
`sync`. Re-run the command to get a fresh plan.

## Install

`skill/` is the shippable skill package — `SKILL.md` and the CLI, nothing else.
Repository docs and `plans/` deliberately sit outside it, so they are never
copied into a skill directory by a sync.

Link `skill/` into place rather than copying, so an edit here takes effect
immediately with nothing to re-sync:

```sh
git clone https://github.com/loversky02/skill-sync.git ~/Documents/tools/skill-sync
ln -sfn ~/Documents/tools/skill-sync/skill ~/.claude/tools/skill-sync
ln -sfn ~/Documents/tools/skill-sync/skill ~/.claude/skills/skill-sync
```

Then put a wrapper on `PATH`:

```sh
printf '#!/bin/sh\nexec python3 "$HOME/.claude/tools/skill-sync/skill_sync.py" "$@"\n' > ~/.local/bin/skill-sync
chmod +x ~/.local/bin/skill-sync
```

Because `~/.claude/skills/skill-sync` is a symlink into a git checkout, a sync
would otherwise carry `.git` into the destination; copies skip the same build
artefacts the drift hash ignores, so they do not.

## Tests

```sh
python3 -m pytest skill/test_skill_sync.py -q
```
