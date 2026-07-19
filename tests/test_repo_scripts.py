import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


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


def test_static_builds_use_pi_resource_limits_only_during_deploy() -> None:
    import deploy
    import yaml

    config = yaml.safe_load((REPO_ROOT / "apps.yaml").read_text(encoding="utf-8"))
    app = next(app for app in config["apps"] if app["name"] == "Pathfinder")

    assert app["build"] == "npm ci && npm run build"
    assert deploy.pi_build_command(app) == (
        "systemd-run --user --scope -p CPUQuota=200% -p MemoryHigh=1200M "
        "-p MemoryMax=1500M -p MemorySwapMax=0 nice -n 10 ionice -c 2 -n 5 "
        "env NODE_OPTIONS=--max-old-space-size=1024 "
        "sh -c 'npm ci --foreground-scripts --no-progress && npm run build'"
    )


def test_stop_only_targets_managed_service_processes(monkeypatch) -> None:
    import deploy

    required: list[tuple[str, ...]] = []
    commands: list[str] = []
    monkeypatch.setattr(deploy, "require", lambda *cmds: required.append(cmds))
    monkeypatch.setattr(deploy, "run", lambda cmd, cwd=None: commands.append(cmd))

    deploy.cmd_stop([
        {"name": "Static", "type": "static"},
        {"name": "API", "type": "service", "pm2_name": "API"},
    ], ["n8n"])

    assert required == [("pm2",)]
    assert commands == ["pm2 stop API || true", "pm2 stop n8n || true"]


def test_build_does_not_start_apps(monkeypatch) -> None:
    import deploy

    built: list[str] = []
    monkeypatch.setattr(deploy, "require", lambda *cmds: None)
    monkeypatch.setattr(deploy, "pull_and_build", lambda app: built.append(app["name"]))

    deploy.cmd_build([
        {"name": "Static", "type": "static"},
        {"name": "API", "type": "service"},
    ])

    assert built == ["Static", "API"]


def test_build_pulls_compose_images_without_starting_containers(monkeypatch) -> None:
    import deploy

    required: list[tuple[str, ...]] = []
    commands: list[str] = []
    monkeypatch.setattr(deploy, "require", lambda *cmds: required.append(cmds))
    monkeypatch.setattr(deploy, "require_docker_compose", lambda: required.append(("docker compose",)))
    monkeypatch.setattr(deploy, "pull_and_build", lambda app: Path("/tmp/stack"))
    monkeypatch.setattr(deploy, "write_env_file", lambda app, path: Path("/tmp/stack/.env"))
    monkeypatch.setattr(deploy, "compose_command", lambda app, env_file: "docker compose test")
    monkeypatch.setattr(deploy, "run", lambda cmd, cwd=None: commands.append(cmd))

    deploy.cmd_build([{"name": "Stack", "type": "compose"}])

    assert required == [("git",), ("docker compose",)]
    assert commands == ["docker compose test pull"]


def test_start_uses_apps_yaml_order_then_extra_pm2_processes(monkeypatch) -> None:
    import deploy

    started: list[str] = []
    monkeypatch.setattr(deploy, "require", lambda *cmds: None)
    monkeypatch.setattr(deploy, "require_docker_compose", lambda: None)
    monkeypatch.setattr(deploy, "start_static", lambda app, path: started.append(app["name"]))
    monkeypatch.setattr(deploy, "start_service", lambda app, path: started.append(app["name"]))
    monkeypatch.setattr(deploy, "start_compose", lambda app, path: started.append(app["name"]))
    monkeypatch.setattr(deploy, "run", lambda cmd, cwd=None: started.append(cmd))

    deploy.cmd_start([
        {"name": "Static", "type": "static", "deploy_path": "/tmp/static"},
        {"name": "API", "type": "service", "deploy_path": "/tmp/api"},
        {"name": "Stack", "type": "compose", "deploy_path": "/tmp/stack"},
    ], ["n8n"])

    assert started == [
        "Static", "API", "Stack", "pm2 start n8n", "pm2 save --force",
    ]


def test_select_apps_returns_named_app() -> None:
    import deploy

    apps = [
        {"name": "Static", "type": "static"},
        {"name": "Stack", "type": "compose"},
    ]

    assert deploy.select_apps("Stack", apps) == [
        {"name": "Stack", "type": "compose"},
    ]


def test_select_apps_returns_all_apps() -> None:
    import deploy

    apps = [
        {"name": "Static", "type": "static"},
        {"name": "Stack", "type": "compose"},
    ]

    assert deploy.select_apps("all", apps) == apps


def test_select_apps_rejects_unknown_target() -> None:
    import deploy
    import pytest

    apps = [
        {"name": "Static", "type": "static"},
        {"name": "Stack", "type": "compose"},
    ]

    with pytest.raises(
        SystemExit,
        match=r"App 'Missing' not found\. Available: Static, Stack",
    ):
        deploy.select_apps("Missing", apps)

def test_main_deploys_individual_target(monkeypatch, tmp_path) -> None:
    import deploy

    config = tmp_path / "apps.yaml"
    config.write_text(
        """
apps:
  - name: Static
    type: static
  - name: Stack
    type: compose
maintenance:
  stop_pm2_processes:
    - n8n
""",
        encoding="utf-8",
    )

    called: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(deploy, "APPS_YAML", config)
    monkeypatch.setattr(
        deploy,
        "cmd_deploy",
        lambda target, apps: called.append(
            (target, [app["name"] for app in apps]),
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["deploy.py", "deploy", "Stack"],
    )

    deploy.main()

    assert called == [("Stack", ["Static", "Stack"])]

def test_restaurant_post_deploy_succeeds_without_backup_database(tmp_path) -> None:
    import yaml

    config = yaml.safe_load((REPO_ROOT / "apps.yaml").read_text(encoding="utf-8"))
    app = next(app for app in config["apps"] if app["name"] == "RestaurantApp")

    result = subprocess.run(
        app["post_deploy_cmd"],
        shell=True,
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "src/main/resources").is_dir()


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
