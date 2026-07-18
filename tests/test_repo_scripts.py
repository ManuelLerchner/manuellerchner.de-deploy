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
    assert "panic.manuellerchner.de {" in caddyfile
    assert "reverse_proxy localhost:18080" in caddyfile


def test_panic_compose_config_uses_ollama_only() -> None:
    import yaml

    config = yaml.safe_load((REPO_ROOT / "apps.yaml").read_text(encoding="utf-8"))
    app = next(app for app in config["apps"] if app["name"] == "PanicAtTheConsole")

    assert app["env"]["LLM_PROVIDER"] == "ollama"
    assert app["env"]["LLM_FALLBACK_ENABLED"] == "false"
    assert not any(key.startswith("LOGOS_") for key in app["env"])
    assert app["compose_overrides"] == ["compose-overrides/panic-at-the-console.yml"]
    assert (REPO_ROOT / app["compose_overrides"][0]).is_file()
