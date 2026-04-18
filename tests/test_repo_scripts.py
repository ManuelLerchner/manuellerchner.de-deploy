import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cmd(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_lint_passes_for_current_config() -> None:
    result = run_cmd("scripts/lint.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no errors" in result.stdout.lower()


def test_gen_readme_uses_correct_regeneration_command() -> None:
    result = run_cmd("scripts/gen_readme.py")
    assert result.returncode == 0, result.stdout + result.stderr

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "python3 scripts/gen_readme.py" in readme


def test_gen_caddyfile_contains_expected_domains() -> None:
    result = run_cmd("scripts/gen_caddyfile.py")
    assert result.returncode == 0, result.stdout + result.stderr

    caddyfile = (REPO_ROOT / "Caddyfile").read_text(encoding="utf-8")
    assert "manuellerchner.de {" in caddyfile
    assert "api.manuellerchner.de {" in caddyfile
