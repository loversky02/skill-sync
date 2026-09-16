#!/usr/bin/env python3
"""Report and synchronize Claude and Codex skill directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# Build artefacts that would otherwise register as spurious drift.
NOISE_NAMES = frozenset({"__pycache__", ".git", ".DS_Store"})
NOISE_SUFFIXES = frozenset({".pyc", ".pyo"})

BUCKETS = (
    "in_sync",
    "only_in_claude",
    "only_in_codex",
    "plugin_provided",
    "content_differs",
)


class SkillSyncError(Exception):
    """A user-facing filesystem or configuration error."""


@dataclass(frozen=True)
class Paths:
    claude: Path
    codex: Path
    plugins: Path


def readable_directory(path: Path, label: str, *, optional: bool = False) -> bool:
    """Validate a directory before scanning it; return False for an absent optional path."""
    if not path.exists():
        if optional:
            return False
        raise SkillSyncError(f"{label} directory does not exist: {path}")
    if not path.is_dir():
        raise SkillSyncError(f"{label} path is not a directory: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    read_bits = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
    execute_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    if mode & read_bits == 0 or mode & execute_bits == 0:
        raise SkillSyncError(f"{label} directory is not readable: {path}")
    return True


def tree_hash(skill_dir: Path) -> str:
    """Hash every file in the skill tree.

    Hashing SKILL.md alone would miss drift in references/, agents/, and scripts/,
    which is the exact false negative this tool exists to prevent. Relative paths
    are folded into the digest so a rename counts as drift.
    """
    digest = hashlib.sha256()
    for path in sorted(skill_dir.rglob("*")):
        relative = path.relative_to(skill_dir)
        if any(part in NOISE_NAMES for part in relative.parts):
            continue
        if path.suffix in NOISE_SUFFIXES or not path.is_file():
            continue
        digest.update(relative.as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def skill_hashes(root: Path, label: str) -> dict[str, str]:
    """Return whole-tree hashes for non-private skill directories under root."""
    readable_directory(root, label)
    skills: dict[str, str] = {}
    try:
        entries = sorted(root.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise SkillSyncError(f"cannot read {label} directory {root}: {exc}") from exc

    for entry in entries:
        if entry.name.startswith("_") or not entry.is_dir():
            continue
        # SKILL.md still defines skill identity; the hash now covers the whole tree.
        if not (entry / "SKILL.md").is_file():
            continue
        try:
            skills[entry.name] = tree_hash(entry)
        except OSError as exc:
            raise SkillSyncError(f"cannot read skill directory {entry}: {exc}") from exc
    return skills


def plugin_skill_names(root: Path) -> set[str]:
    """Find skill directories below each plugin version's skills directory."""
    if not readable_directory(root, "plugins", optional=True):
        return set()
    names: set[str] = set()
    try:
        for skills_root in root.glob("*/*/*/skills"):
            if not skills_root.is_dir():
                continue
            for skill_file in skills_root.rglob("SKILL.md"):
                skill_dir = skill_file.parent
                if not skill_dir.name.startswith("_") and skill_dir.is_dir():
                    names.add(skill_dir.name)
    except OSError as exc:
        raise SkillSyncError(f"cannot read plugins directory {root}: {exc}") from exc
    return names


def build_report(paths: Paths) -> dict[str, list[str]]:
    claude = skill_hashes(paths.claude, "Claude skills")
    codex = skill_hashes(paths.codex, "Codex skills")
    plugin_names = plugin_skill_names(paths.plugins)
    report = {bucket: [] for bucket in BUCKETS}

    for name in sorted(claude.keys() | codex.keys()):
        if name in claude and name in codex:
            bucket = "in_sync" if claude[name] == codex[name] else "content_differs"
        elif name in claude:
            bucket = "only_in_claude"
        elif name in plugin_names:
            bucket = "plugin_provided"
        else:
            bucket = "only_in_codex"
        report[bucket].append(name)
    return report


def print_report(report: dict[str, list[str]]) -> None:
    for bucket in BUCKETS:
        names = report[bucket]
        print(f"{bucket} ({len(names)}):")
        for name in names:
            print(f"  {name}")


def copy_skill(source_root: Path, target_root: Path, name: str) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_root / name, target_root / name, dirs_exist_ok=True)


def sync(paths: Paths, report: dict[str, list[str]], target: str, apply: bool, force: bool) -> None:
    if target == "codex":
        source_root = paths.claude
        target_root = paths.codex
        missing = report["only_in_claude"]
    else:
        source_root = paths.codex
        target_root = paths.claude
        missing = report["only_in_codex"]

    overwrites = report["content_differs"] if force else []
    skipped = [] if force else report["content_differs"]
    print(f"mode: {'apply' if apply else 'dry-run'}")
    print(f"target: {target_root}")
    print_names("copy", missing)
    print_names("overwrite", overwrites)
    print_names("skipped_content_differs", skipped)

    if not apply:
        return
    # The plan above was computed from an earlier scan. Re-read both trees
    # immediately before writing: if either side changed in between, the plan is
    # stale and copying it would act on a picture of the skills that no longer
    # holds. Abort rather than write against it.
    if build_report(paths) != report:
        raise SkillSyncError(
            "skill directories changed while the plan was being prepared; "
            "nothing was copied - re-run to see the current plan"
        )
    for name in (*missing, *overwrites):
        copy_skill(source_root, target_root, name)


def print_names(label: str, names: Iterable[str]) -> None:
    values = list(names)
    print(f"{label} ({len(values)}):")
    for name in values:
        print(f"  {name}")


def path_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--claude-dir",
        type=Path,
        default=Path("~/.claude/skills").expanduser(),
        help="Claude user-skill directory (default: ~/.claude/skills)",
    )
    parser.add_argument(
        "--codex-dir",
        type=Path,
        default=Path("~/.codex/skills").expanduser(),
        help="Codex skill directory (default: ~/.codex/skills)",
    )
    parser.add_argument(
        "--plugins-dir",
        type=Path,
        default=Path("~/.claude/plugins/cache").expanduser(),
        help="Claude plugin cache directory (default: ~/.claude/plugins/cache)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skill-sync")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report_parser = subparsers.add_parser("report", help="report skill drift")
    path_options(report_parser)
    report_parser.add_argument("--json", action="store_true", help="emit JSON")

    sync_parser = subparsers.add_parser("sync", help="copy missing or stale skills")
    path_options(sync_parser)
    sync_parser.add_argument("--to", choices=("claude", "codex"), required=True)
    sync_parser.add_argument("--apply", action="store_true", help="perform writes")
    sync_parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite skills whose SKILL.md content differs (requires --apply to write)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    paths = Paths(
        args.claude_dir.expanduser(),
        args.codex_dir.expanduser(),
        args.plugins_dir.expanduser(),
    )
    try:
        report = build_report(paths)
        if args.command == "report":
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print_report(report)
        else:
            sync(paths, report, args.to, args.apply, args.force)
    except SkillSyncError as exc:
        print(f"skill-sync: error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
