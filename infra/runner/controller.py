"""Trusted runner entry point. Artifacts run only after isolation and hash checks."""

import base64
import hashlib
import io
import json
import os
import runpy
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import sync_playwright

from runner_contract import ProductFailure


class BoundedOutput(io.StringIO):
    def write(self, text):
        if self.tell() + len(text) > 4096:
            raise RuntimeError("Artifact output limit exceeded")
        return super().write(text)


def check_process_controls():
    status = dict(
        line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    if os.getuid() != 1001 or status["NoNewPrivs"].strip() != "1":
        raise RuntimeError("Non-root/no-new-privileges check failed")
    if int(status["CapEff"].strip(), 16) != 0 or status["Seccomp"].strip() != "2":
        raise RuntimeError("Capabilities/seccomp check failed")
    if any(line.split()[1] == "00000000" for line in Path("/proc/net/route").read_text().splitlines()[1:]):
        raise RuntimeError("A default network route is present")
    if Path("/proc/sys/net/ipv6/conf/all/disable_ipv6").read_text().strip() != "1":
        raise RuntimeError("IPv6 must be disabled")


def check_browser_sandbox():
    found = False
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").split()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if not command or b"/ms-playwright/" not in command[0] or b"chrome" not in command[0]:
            continue
        found = True
        if b"--no-sandbox" in command or b"--disable-setuid-sandbox" in command:
            raise RuntimeError("Chromium sandbox disabling argument detected")
    if not found:
        raise RuntimeError("Chromium process could not be verified")


def check_renderer_isolation():
    """Check an actual renderer, rather than only browser launch arguments."""
    own_status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    renderers = 0
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").split()
            if b"--type=renderer" not in command:
                continue
            status = dict(
                line.split(":", 1) for line in (entry / "status").read_text().splitlines()
                if ":" in line
            )
            pid_depth = len(status["NSpid"].split())
        except (FileNotFoundError, ProcessLookupError):
            continue
        if (
            status["NoNewPrivs"].strip() != "1"
            or int(status["CapEff"].strip(), 16) != 0
            or status["Seccomp"].strip() != "2"
            or pid_depth <= len(own_status["NSpid"].split())
            or int(status["Seccomp_filters"].strip()) <= int(own_status["Seccomp_filters"].strip())
        ):
            raise RuntimeError("Renderer sandbox controls could not be verified")
        renderers += 1
    if not renderers:
        raise RuntimeError("No isolated Chromium renderer could be verified")
    return renderers


def main():
    report = {"outcome": "infrastructure_error", "code_executed": False, "screenshot_base64": None}
    browser = None
    page = None
    try:
        check_process_controls()
        opener = build_opener(ProxyHandler({}))
        deadline = time.monotonic() + 10
        while True:
            try:
                with opener.open("http://demo:8000/", timeout=1) as response:
                    if response.status != 200:
                        raise RuntimeError("Demo readiness response was not HTTP 200")
                break
            except (URLError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Owned demo did not become ready within 10 seconds")
                time.sleep(0.2)
        Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(chromium_sandbox=True)
            check_browser_sandbox()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_default_timeout(10000)
            page.set_default_navigation_timeout(15000)
            response = page.goto("http://demo:8000/", wait_until="domcontentloaded")
            if response is None or response.status != 200:
                raise RuntimeError("Owned demo is unavailable")
            page.evaluate("document.body.textContent.length")
            report["isolated_renderers"] = check_renderer_isolation()
            report["sandbox_verified"] = True
            if sys.argv[1:] == ["--preflight"]:
                report.update(outcome="ready", sandbox_verified=True)
            elif len(sys.argv) == 3 and sys.argv[1] == "--run":
                artifact = Path("/artifact/scenario.py")
                if hashlib.sha256(artifact.read_bytes()).hexdigest() != sys.argv[2]:
                    raise RuntimeError("Executable artifact digest mismatch")
                captured = BoundedOutput()
                try:
                    report["code_executed"] = True
                    with redirect_stdout(captured), redirect_stderr(captured):
                        module = runpy.run_path(str(artifact))
                        module["run"](page)
                    report["outcome"] = "passed"
                except ProductFailure as exc:
                    report.update(outcome="product_failure", detail=str(exc)[:1000])
                except Exception as exc:
                    report.update(outcome="test_failure", detail=f"{type(exc).__name__}: {str(exc)[-3000:]}")
                report["artifact_output"] = captured.getvalue()
                screenshot = page.screenshot(type="png", full_page=True)
                if len(screenshot) > 1_000_000:
                    raise RuntimeError("Screenshot size limit exceeded")
                report["screenshot_base64"] = base64.b64encode(screenshot).decode("ascii")
            else:
                raise RuntimeError("Unsupported runner invocation")
            browser.close()
    except Exception as exc:
        report.update(outcome="infrastructure_error", detail=f"{type(exc).__name__}: {str(exc)[-3000:]}")
    print(json.dumps(report), flush=True)
    return 0 if report["outcome"] in {"passed", "ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

