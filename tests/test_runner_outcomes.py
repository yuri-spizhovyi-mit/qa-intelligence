"""Report classification checks; browser, isolation and artifact execution are mocked."""

import base64
import hashlib
import importlib.util
import json
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch, tmp_path):
    directory = Path(__file__).resolve().parents[1] / "infra" / "runner"
    monkeypatch.syspath_prepend(str(directory))
    spec = importlib.util.spec_from_file_location("trusted_runner_outcomes", directory / "controller.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    state = SimpleNamespace(executions=0, reads=0, browser_closed=False)
    artifact_bytes = b"unexecuted synthetic fixture"

    class Artifact:
        def read_bytes(self):
            state.reads += 1
            return artifact_bytes

        def __str__(self):
            return "/artifact/scenario.py"

    real_path = module.Path
    monkeypatch.setattr(module, "Path", lambda value: Artifact() if value == "/artifact/scenario.py" else real_path(value))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(module, "check_process_controls", lambda: None)
    monkeypatch.setattr(module, "check_browser_sandbox", lambda: None)
    monkeypatch.setattr(module, "check_renderer_isolation", lambda: 1)

    page = SimpleNamespace(
        set_default_timeout=lambda value: None,
        set_default_navigation_timeout=lambda value: None,
        goto=lambda *args, **kwargs: SimpleNamespace(status=200),
        evaluate=lambda expression: 10,
        screenshot=lambda **kwargs: b"synthetic screenshot bytes",
    )

    def close():
        state.browser_closed = True

    browser = SimpleNamespace(new_page=lambda **kwargs: page, close=close)

    def launch(**kwargs):
        assert kwargs == {"chromium_sandbox": True}
        return browser

    chromium = SimpleNamespace(launch=launch)
    monkeypatch.setattr(module, "sync_playwright", lambda: nullcontext(SimpleNamespace(chromium=chromium)))
    monkeypatch.setattr(module, "build_opener", lambda *args: SimpleNamespace(
        open=lambda *args, **kwargs: nullcontext(SimpleNamespace(status=200))
    ))

    def run(page_argument):
        assert page_argument is page
        state.executions += 1

    def load_artifact(path):
        assert path == "/artifact/scenario.py"
        return {"run": run}

    # The real run_path is never called: no fixture code is imported or executed.
    monkeypatch.setattr(module.runpy, "run_path", load_artifact)
    digest = hashlib.sha256(artifact_bytes).hexdigest()
    monkeypatch.setattr(sys, "argv", ["controller.py", "--run", digest])
    return SimpleNamespace(module=module, state=state, page=page, chromium=chromium)


def result(runner, capsys):
    exit_code = runner.module.main()
    return exit_code, json.loads(capsys.readouterr().out)


def fail(message, exception=RuntimeError):
    def raise_error(*args, **kwargs):
        raise exception(message)
    return raise_error


def test_success_is_reported_with_screenshot(runner, capsys):
    exit_code, report = result(runner, capsys)
    assert exit_code == 0
    assert report["outcome"] == "passed"
    assert report["code_executed"] is True
    assert report["sandbox_verified"] is True
    assert base64.b64decode(report["screenshot_base64"]) == b"synthetic screenshot bytes"
    assert runner.state.executions == 1
    assert runner.state.browser_closed is True


def test_observed_status_mismatch_is_product_failure(runner, monkeypatch, capsys):
    monkeypatch.setattr(runner.module.runpy, "run_path", lambda path: {
        "run": fail("Expected HTTP 201, observed 422", runner.module.ProductFailure)
    })
    exit_code, report = result(runner, capsys)
    assert exit_code == 1
    assert report["outcome"] == "product_failure"
    assert report["code_executed"] is True
    assert report["detail"] == "Expected HTTP 201, observed 422"
    assert report["screenshot_base64"] is not None


def test_locator_failure_is_test_failure(runner, monkeypatch, capsys):
    monkeypatch.setattr(runner.module.runpy, "run_path", lambda path: {
        "run": fail("Submit control was not found")
    })
    exit_code, report = result(runner, capsys)
    assert exit_code == 1
    assert report["outcome"] == "test_failure"
    assert report["code_executed"] is True
    assert "Submit control was not found" in report["detail"]


def test_artifact_load_error_is_test_failure(runner, monkeypatch, capsys):
    monkeypatch.setattr(runner.module.runpy, "run_path", fail("Invalid fixture module", SyntaxError))
    exit_code, report = result(runner, capsys)
    assert exit_code == 1
    assert report["outcome"] == "test_failure"
    assert "SyntaxError" in report["detail"]


def test_browser_startup_failure_prevents_artifact_execution(runner, monkeypatch, capsys):
    monkeypatch.setattr(runner.chromium, "launch", fail("Browser could not start"))
    exit_code, report = result(runner, capsys)
    assert exit_code == 1
    assert report["outcome"] == "infrastructure_error"
    assert report["code_executed"] is False
    assert runner.state.reads == runner.state.executions == 0


def test_failed_isolation_check_prevents_browser_launch(runner, monkeypatch, capsys):
    monkeypatch.setattr(runner.module, "check_process_controls", fail("Unexpected default route"))
    monkeypatch.setattr(runner.chromium, "launch", fail("Must not reach browser"))
    exit_code, report = result(runner, capsys)
    assert exit_code == 1
    assert report["outcome"] == "infrastructure_error"
    assert "Unexpected default route" in report["detail"]
    assert report["code_executed"] is False
    assert runner.state.reads == runner.state.executions == 0


def test_digest_mismatch_prevents_artifact_load(runner, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["controller.py", "--run", "0" * 64])
    exit_code, report = result(runner, capsys)
    assert exit_code == 1
    assert report["outcome"] == "infrastructure_error"
    assert report["detail"].endswith("Executable artifact digest mismatch")
    assert report["code_executed"] is False
    assert runner.state.executions == 0


def test_screenshot_failure_does_not_leave_a_pass(runner, monkeypatch, capsys):
    monkeypatch.setattr(runner.page, "screenshot", fail("Screenshot capture failed"))
    exit_code, report = result(runner, capsys)
    assert exit_code == 1
    assert report["outcome"] == "infrastructure_error"
    assert report["code_executed"] is True
    assert report["screenshot_base64"] is None
    assert runner.state.executions == 1


def test_preflight_never_loads_artifact(runner, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["controller.py", "--preflight"])
    exit_code, report = result(runner, capsys)
    assert exit_code == 0
    assert report["outcome"] == "ready"
    assert report["sandbox_verified"] is True
    assert report["code_executed"] is False
    assert runner.state.reads == runner.state.executions == 0
