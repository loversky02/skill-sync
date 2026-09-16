import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("skill_sync.py")
sys.path.insert(0, str(SCRIPT.parent))

import skill_sync  # noqa: E402  (needs the path insert above)


def make_skill(root: Path, name: str, content: str, extra: str | None = None) -> Path:
    skill = root / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(content)
    if extra is not None:
        (skill / "extra.txt").write_text(extra)
    return skill


def run_cli(claude: Path, codex: Path, plugins: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *arguments,
            "--claude-dir",
            str(claude),
            "--codex-dir",
            str(codex),
            "--plugins-dir",
            str(plugins),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def empty_layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    claude = tmp_path / "claude"
    codex = tmp_path / "codex"
    plugins = tmp_path / "plugins"
    for directory in (claude, codex, plugins):
        directory.mkdir()
    return claude, codex, plugins


def test_report_classifies_all_five_buckets(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "same", "same")
    make_skill(codex, "same", "same")
    make_skill(claude, "claude-only", "claude")
    make_skill(codex, "codex-only", "codex")
    make_skill(claude, "different", "left")
    make_skill(codex, "different", "right")
    make_skill(codex, "plugin-skill", "codex")
    make_skill(
        plugins / "market" / "plugin" / "1.0" / "skills" / "category",
        "plugin-skill",
        "plugin",
    )

    result = run_cli(claude, codex, plugins, "report", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "content_differs": ["different"],
        "in_sync": ["same"],
        "only_in_claude": ["claude-only"],
        "only_in_codex": ["codex-only"],
        "plugin_provided": ["plugin-skill"],
    }


def test_plugin_provided_skill_is_never_synced_to_claude(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(codex, "code-review", "codex")
    make_skill(plugins / "market" / "bundle" / "2.0" / "skills", "code-review", "plugin")

    result = run_cli(claude, codex, plugins, "sync", "--to", "claude", "--apply")

    assert result.returncode == 0, result.stderr
    assert not (claude / "code-review").exists()
    assert "copy (0)" in result.stdout


def test_sync_without_apply_makes_no_writes(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "new-skill", "new", extra="whole tree")
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = run_cli(claude, codex, plugins, "sync", "--to", "codex")

    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert result.returncode == 0, result.stderr
    assert before == after
    assert not (codex / "new-skill").exists()
    assert "mode: dry-run" in result.stdout


def test_apply_copies_whole_skill_tree_in_either_direction(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "to-codex", "a", extra="claude extra")
    make_skill(codex, "to-claude", "b", extra="codex extra")

    to_codex = run_cli(claude, codex, plugins, "sync", "--to", "codex", "--apply")
    to_claude = run_cli(claude, codex, plugins, "sync", "--to", "claude", "--apply")

    assert to_codex.returncode == to_claude.returncode == 0
    assert (codex / "to-codex" / "extra.txt").read_text() == "claude extra"
    assert (claude / "to-claude" / "extra.txt").read_text() == "codex extra"


def test_content_difference_requires_apply_and_force_to_overwrite(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "stale", "source")
    make_skill(codex, "stale", "destination")

    applied = run_cli(claude, codex, plugins, "sync", "--to", "codex", "--apply")
    forced_dry_run = run_cli(claude, codex, plugins, "sync", "--to", "codex", "--force")
    assert (codex / "stale" / "SKILL.md").read_text() == "destination"
    assert "skipped_content_differs (1)" in applied.stdout
    assert "mode: dry-run" in forced_dry_run.stdout

    forced = run_cli(claude, codex, plugins, "sync", "--to", "codex", "--apply", "--force")

    assert forced.returncode == 0, forced.stderr
    assert (codex / "stale" / "SKILL.md").read_text() == "source"


def test_force_overwrite_never_deletes_destination_files(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "stale", "source")
    destination = make_skill(codex, "stale", "destination")
    (destination / "destination-only.txt").write_text("keep me")

    result = run_cli(
        claude,
        codex,
        plugins,
        "sync",
        "--to",
        "codex",
        "--apply",
        "--force",
    )

    assert result.returncode == 0, result.stderr
    assert (destination / "destination-only.txt").read_text() == "keep me"


def test_private_directories_and_non_directories_are_skipped(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "_shared", "private")
    (claude / "plain-file").write_text("not a skill")

    result = run_cli(claude, codex, plugins, "report", "--json")

    assert result.returncode == 0, result.stderr
    assert all(not names for names in json.loads(result.stdout).values())


def test_drift_below_skill_md_is_detected(tmp_path: Path) -> None:
    """Identical SKILL.md but divergent references/ must not report in_sync."""
    claude, codex, plugins = empty_layout(tmp_path)
    left = make_skill(claude, "deep", "identical")
    right = make_skill(codex, "deep", "identical")
    (left / "references").mkdir()
    (right / "references").mkdir()
    (left / "references" / "note.md").write_text("original")
    (right / "references" / "note.md").write_text("edited")

    result = run_cli(claude, codex, plugins, "report", "--json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["content_differs"] == ["deep"]
    assert report["in_sync"] == []


def test_renamed_support_file_counts_as_drift(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    left = make_skill(claude, "renamed", "identical")
    right = make_skill(codex, "renamed", "identical")
    (left / "guide.md").write_text("body")
    (right / "manual.md").write_text("body")

    result = run_cli(claude, codex, plugins, "report", "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["content_differs"] == ["renamed"]


def test_build_artefacts_do_not_create_false_drift(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "noisy", "identical")
    right = make_skill(codex, "noisy", "identical")
    cache = right / "__pycache__"
    cache.mkdir()
    (cache / "helper.cpython-313.pyc").write_bytes(b"\x00compiled")
    (right / ".DS_Store").write_bytes(b"\x00finder")

    result = run_cli(claude, codex, plugins, "report", "--json")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["in_sync"] == ["noisy"]
    assert report["content_differs"] == []


def test_apply_aborts_when_the_plan_no_longer_matches_disk(tmp_path: Path) -> None:
    """A plan built before the directories changed must not be written."""
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "real", "a")
    paths = skill_sync.Paths(claude, codex, plugins)
    stale = {bucket: [] for bucket in skill_sync.BUCKETS}
    stale["only_in_claude"] = ["real", "disappeared-since-the-scan"]

    with pytest.raises(skill_sync.SkillSyncError, match="nothing was copied"):
        skill_sync.sync(paths, stale, "codex", apply=True, force=False)

    assert not (codex / "real").exists()


def test_apply_proceeds_when_the_plan_still_matches_disk(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    make_skill(claude, "real", "a")
    paths = skill_sync.Paths(claude, codex, plugins)

    skill_sync.sync(paths, skill_sync.build_report(paths), "codex", apply=True, force=False)

    assert (codex / "real" / "SKILL.md").read_text() == "a"


def test_missing_source_directory_returns_clean_error(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    missing = tmp_path / "missing"

    result = run_cli(missing, codex, plugins, "report")

    assert result.returncode == 2
    assert "does not exist" in result.stderr
    assert "Traceback" not in result.stderr


def test_unreadable_source_directory_returns_clean_error(tmp_path: Path) -> None:
    claude, codex, plugins = empty_layout(tmp_path)
    original_mode = claude.stat().st_mode
    claude.chmod(0)
    try:
        result = run_cli(claude, codex, plugins, "report")
    finally:
        claude.chmod(original_mode)

    assert result.returncode == 2
    assert "not readable" in result.stderr
    assert "Traceback" not in result.stderr
