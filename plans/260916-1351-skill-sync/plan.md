# skill-sync — drift reporter for Claude ↔ Codex skills

## Outcome

A CLI that reports drift between `~/.claude/skills/` and `~/.codex/skills/`, and
can copy missing or stale skills either direction. Dry-run by default.

## Why

The user mirrors skills between the two agents by hand. Live counts: 289 dirs in
`~/.claude/skills/`, 41 in `~/.codex/skills/`. Drift is already real and silent.

## The trap this must not fall into

Claude serves skills from **two** places:

1. `~/.claude/skills/<name>/SKILL.md` — user skills
2. `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/skills/<name>/SKILL.md` — plugin skills

Skills such as `code-review`, `grilling`, `diagnosing-bugs`, `domain-modeling`
exist in `~/.codex/skills/` and are available to Claude **via plugins**. A naive
two-directory comparison reports these as "missing from Claude" and would push
duplicates into `~/.claude/skills/`, shadowing the managed plugin copies.

Plugin-provided skills must be detected and reported in their own bucket, never
in `only_in_codex`, and never auto-synced.

## Scope

Files (all new, under `tools/skill-sync/`):

- `skill_sync.py` — CLI
- `test_skill_sync.py` — pytest suite
- `README.md` — usage

Python 3.13.7, stdlib only. No third-party deps.

## Behaviour

    skill-sync report                  # default: dry-run drift report
    skill-sync report --json           # machine-readable
    skill-sync sync --to codex         # copy only_in_claude → ~/.codex/skills/
    skill-sync sync --to claude        # copy only_in_codex → ~/.claude/skills/
    skill-sync sync --to codex --apply # actually write; without --apply, print plan only

Buckets in the report:

| Bucket | Meaning |
|---|---|
| `in_sync` | same name, identical `SKILL.md` content hash |
| `only_in_claude` | user skill absent from Codex |
| `only_in_codex` | absent from Claude **and** not provided by any plugin |
| `plugin_provided` | in Codex, and in Claude via a plugin — informational, never synced |
| `content_differs` | both sides have it, `SKILL.md` hashes differ |

Comparison key: directory name. Drift signal: SHA-256 of `SKILL.md` bytes.
Skill identity is the directory; sync copies the whole directory tree.

## Constraints

- `--apply` is the only thing that may write outside the repo. Everything else is
  read-only.
- Never delete on either side. Sync adds and overwrites only.
- Overwriting a `content_differs` skill requires `--apply --force`; plain
  `--apply` skips them and lists them.
- Ignore entries starting with `_` (e.g. `_shared`) and any non-directory.
- Paths configurable via `--claude-dir` / `--codex-dir` so tests never touch the
  user's real directories.

## Validation

    python3 -m pytest tools/skill-sync/test_skill_sync.py -q

Tests must cover, using tmp_path fixtures only: each of the five buckets, the
plugin-provided false-positive case, `--apply` gating, `--force` gating, the `_`
prefix skip, and a missing/unreadable source directory.

## Acceptance criteria

1. `report` against the user's real dirs runs clean and classifies
   `code-review` / `grilling` as `plugin_provided`, not `only_in_codex`.
2. Test suite passes.
3. No write occurs without `--apply`; proven by a test.
4. Zero third-party imports.

## Non-goals

- Bidirectional merge or conflict resolution
- Watching/daemon mode
- Touching `AGENTS.md`, `CLAUDE.md`, or plugin caches
- Deleting anything, ever
