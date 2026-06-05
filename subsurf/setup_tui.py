"""Textual setup app for SubSurf."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from subsurf import demo, wizard


try:
    from rich.markup import escape
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, VerticalScroll
    from textual.widgets import Button, Footer, Header, Log, ProgressBar, Static
except ImportError as exc:  # pragma: no cover - exercised when optional dep is absent
    App = object  # type: ignore[assignment,misc]
    ComposeResult = Any  # type: ignore[misc,assignment]
    Container = Horizontal = Vertical = VerticalScroll = object  # type: ignore[misc,assignment]
    Button = Footer = Header = Log = ProgressBar = Static = object  # type: ignore[misc,assignment]
    TEXTUAL_IMPORT_ERROR: ImportError | None = exc

    def escape(value: object) -> str:  # type: ignore[no-redef]
        return str(value)

else:
    TEXTUAL_IMPORT_ERROR = None


STEP_LABELS: dict[str, str] = {
    "preflight": "Preflight",
    "login": "Claude Login",
    "publish": "OAuth Token",
    "keepalive": "Keepalive",
    "sample": "Sample App",
    "python": "Python Piggyback",
    "gateway": "Gateway Piggyback",
}
STEP_ORDER = tuple(STEP_LABELS)
STEP_DETAILS = {
    "preflight": "Tools, paths, and isolated state",
    "login": "Claude opens with SubSurf config",
    "publish": "Token copied into install state",
    "keepalive": "Refresh daemon prepared",
    "sample": "Example app files written",
    "python": "Direct SDK-style piggyback call",
    "gateway": "OpenAI-compatible gateway check",
}
STEP_STATUS = {
    "WAIT": "PENDING",
    "RUN": "RUNNING",
    "OK": "COMPLETE",
    "FAIL": "FAILED",
}


@dataclass(frozen=True)
class CapturedResult:
    value: Any
    output: str


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch the SubSurf Textual setup app")
    parser.add_argument("--account-id")
    parser.add_argument("--app-dir", default=wizard.DEFAULT_ATTACH_DIR)
    parser.add_argument("--no-start-daemon", action="store_true")
    parser.add_argument("--skip-login", action="store_true")
    parser.add_argument("--no-overwrite-attach", action="store_true")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--install-id-file", default=wizard.DEFAULT_INSTALL_ID_FILE, help=argparse.SUPPRESS)
    return parser


def auto_wizard_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        account_id=args.account_id,
        label=args.account_id,
        config_dir=None,
        install_id_file=args.install_id_file,
        token_file=None,
        accounts_file=None,
        pool_file=None,
        interval=60,
        manual=False,
        skip_login=args.skip_login,
        allow_shared_claude_config=False,
        launch_claude=None,
        start_daemon=not args.no_start_daemon,
        attach_dir=args.app_dir,
        overwrite_attach=not args.no_overwrite_attach,
        status=False,
    )


def main(argv: list[str] | None = None) -> int:
    if TEXTUAL_IMPORT_ERROR is not None:
        print("SubSurf setup TUI requires Textual.")
        print("Install it with:")
        print("  python -m pip install -e '.[tui]'")
        return 2

    args = build_parser().parse_args(argv)
    SubSurfSetupApp(args).run()
    return 0


class SubSurfSetupApp(App):  # type: ignore[misc]
    """Polished setup flow for SubSurf."""

    TITLE = "SubSurf Setup"
    SUB_TITLE = "Isolated Claude Code OAuth"

    CSS = """
    Screen {
        background: #11110f;
        color: #ede9de;
    }

    Header {
        background: #191814;
        color: #ede9de;
    }

    Footer {
        background: #191814;
        color: #bbb4a6;
    }

    #shell {
        height: 100%;
        padding: 1 2;
    }

    #hero {
        height: 5;
        padding: 1 2;
        border: tall #d6b35f;
        background: #191814;
    }

    #hero-head {
        height: 1;
    }

    #brand {
        width: 1fr;
        text-style: bold;
        color: #fff6cf;
    }

    #run-state {
        width: 28;
        text-align: right;
        color: #89d6b4;
    }

    #tagline {
        color: #bbb4a6;
        margin-top: 1;
    }

    #summary {
        height: 4;
        margin-top: 1;
    }

    .metric {
        width: 1fr;
        height: 4;
        margin-right: 1;
        padding: 0 1;
        border: tall #333026;
        background: #171713;
    }

    #metric-model {
        margin-right: 0;
    }

    #actions {
        height: 3;
        margin-top: 1;
    }

    Button {
        margin-right: 1;
    }

    #content {
        height: 1fr;
        margin-top: 1;
    }

    #left-pane {
        width: 48;
        margin-right: 1;
    }

    #progress-panel {
        height: 5;
        padding: 0 1;
        border: tall #333026;
        background: #171713;
    }

    #progress-label {
        height: 1;
        color: #bbb4a6;
    }

    ProgressBar {
        margin-top: 1;
    }

    #steps {
        height: 1fr;
        margin-top: 1;
    }

    .step {
        height: 3;
        padding: 0 1;
        border: tall #2f2c23;
        background: #151512;
        color: #c9c2b4;
    }

    .step.running {
        border: tall #d6b35f;
        background: #1f1b12;
        color: #fff6cf;
    }

    .step.ok {
        border: tall #48c78e;
        color: #d7f4e6;
    }

    .step.fail {
        border: tall #ff6b6b;
        background: #231513;
        color: #ffd0cc;
    }

    #right-pane {
        width: 1fr;
    }

    .section-title {
        height: 1;
        color: #bbb4a6;
        text-style: bold;
    }

    #log {
        height: 1fr;
        width: 1fr;
        padding: 0 1;
        border: tall #333026;
        background: #0c0c0b;
        color: #d8d2c6;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "start", "Start"),
        ("d", "demo", "Checks"),
    ]

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.args = args
        self.options: wizard.WizardOptions | None = None
        self.running = False
        self.step_states = {key: "WAIT" for key in STEP_ORDER}
        self.current_step: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="shell"):
            with Vertical(id="hero"):
                with Horizontal(id="hero-head"):
                    yield Static("SubSurf", id="brand")
                    yield Static("READY", id="run-state")
                yield Static(
                    "Isolated Claude Code OAuth setup with keepalive and live piggyback checks.",
                    id="tagline",
                )
            with Horizontal(id="summary"):
                yield Static(
                    self.metric_text("ACCOUNT", "pending", "generated locally"),
                    id="metric-account",
                    classes="metric",
                )
                yield Static(
                    self.metric_text("TOKEN", "pending", "per-install file"),
                    id="metric-token",
                    classes="metric",
                )
                yield Static(
                    self.metric_text("MODEL", self.args.model, "live checks"),
                    id="metric-model",
                    classes="metric",
                )
            with Horizontal(id="actions"):
                yield Button("Start Setup", id="start", variant="primary")
                yield Button("Run Checks", id="demo", variant="success")
                yield Button("Quit", id="quit")
            with Horizontal(id="content"):
                with Vertical(id="left-pane"):
                    with Container(id="progress-panel"):
                        yield Static("SETUP PROGRESS", classes="section-title")
                        yield Static("0 of 7 complete", id="progress-label")
                        yield ProgressBar(
                            total=len(STEP_ORDER),
                            show_eta=False,
                            id="progress",
                        )
                    with VerticalScroll(id="steps"):
                        for key, label in STEP_LABELS.items():
                            yield Static(
                                self.step_text(label, "WAIT", STEP_DETAILS[key]),
                                id=f"step-{key}",
                                classes="step",
                            )
                with Vertical(id="right-pane"):
                    yield Static("ACTIVITY", classes="section-title")
                    yield Log(id="log", highlight=True, auto_scroll=True)
        yield Footer()

    def on_mount(self) -> None:
        self.update_progress()
        self.log_line("Ready. Press Start Setup.")
        self.log_line("Generated config, token, and account files avoid clashes automatically.")
        self.log_line("Safety: only run /login in the isolated Claude session opened by setup.")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "quit":
            self.exit()
        elif event.button.id == "start":
            await self.action_start()
        elif event.button.id == "demo":
            await self.action_demo()

    async def action_start(self) -> None:
        if self.running:
            return
        self.running = True
        self.set_buttons(False)
        try:
            await self.setup_flow()
        finally:
            self.running = False
            self.set_buttons(True)

    async def action_demo(self) -> None:
        if self.running:
            return
        self.running = True
        self.set_buttons(False)
        try:
            await self.demo_flow()
        finally:
            self.running = False
            self.set_buttons(True)

    def set_buttons(self, enabled: bool) -> None:
        for button_id in ["#start", "#demo"]:
            self.query_one(button_id, Button).disabled = not enabled

    async def setup_flow(self) -> None:
        try:
            self.reset_steps()
            self.set_run_state("SETUP RUNNING")
            self.update_step("preflight", "RUN", "checking local tools")
            options = self.resolve_options()
            self.options = options
            self.log_options(options)
            self.require_claude_if_needed(options)
            self.update_step("preflight", "OK", "local tools ready")

            self.update_step("login", "RUN", "Claude Code will take over this terminal")
            self.log_line("When Claude opens: run /login, finish browser auth, then /exit.")
            self.log_line("Do not run /login in your normal Claude Code terminal for this setup.")
            if options.skip_login:
                self.log_line("Skipping Claude launch because --skip-login was set.")
            else:
                with self.suspend():
                    wizard.run_claude_login(options)
            self.update_step("login", "OK", "Claude session captured")

            self.update_step("publish", "RUN", "enrolling and publishing token")
            captured = await asyncio.to_thread(capture, wizard.enroll_and_publish, options)
            self.log_output(captured.output)
            self.update_step("publish", "OK", "token file ready")

            self.update_step("keepalive", "RUN", "starting daemon")
            captured = await asyncio.to_thread(capture, wizard.start_daemon, options)
            self.log_output(captured.output)
            self.update_step("keepalive", "OK", "keepalive handled")

            self.update_step("sample", "RUN", "writing sample app")
            captured = await asyncio.to_thread(capture, wizard.attach_app, options)
            self.log_output(captured.output)
            self.update_step("sample", "OK", "sample app ready")

            await self.run_live_checks(options)
            self.notify("SubSurf setup complete", severity="information")
            self.set_run_state("SETUP COMPLETE")
            self.log_line("Done. SubSurf is working.")
        except Exception as exc:
            self.fail_current(exc)

    async def demo_flow(self) -> None:
        try:
            self.set_run_state("CHECKS RUNNING")
            options = self.options or self.resolve_options(skip_login=True, start_daemon=False)
            self.log_options(options)
            await self.run_live_checks(options)
            self.set_run_state("CHECKS PASSED")
            self.notify("SubSurf demo passed", severity="information")
        except Exception as exc:
            self.fail_current(exc)

    async def run_live_checks(self, options: wizard.WizardOptions) -> None:
        demo_paths = self.demo_paths(options)

        self.update_step("python", "RUN", "calling through SubSurfEngine")
        text = await demo._complete_with_engine(
            demo_paths,
            model=self.args.model,
            prompt=demo.DEFAULT_PROMPT,
        )
        self.log_line(f"Python reply: {text.strip()}")
        self.update_step("python", "OK", "direct app call passed")

        self.update_step("gateway", "RUN", "calling local gateway in-process")
        payload = await asyncio.to_thread(
            demo._gateway_completion,
            demo_paths,
            model=self.args.model,
            prompt=demo.DEFAULT_PROMPT,
        )
        self.log_line(f"Gateway reply: {payload['choices'][0]['message']['content'].strip()}")
        self.update_step("gateway", "OK", "gateway call passed")

    def resolve_options(
        self,
        *,
        skip_login: bool | None = None,
        start_daemon: bool | None = None,
    ) -> wizard.WizardOptions:
        args = auto_wizard_args(self.args)
        if skip_login is not None:
            args.skip_login = skip_login
        if start_daemon is not None:
            args.start_daemon = start_daemon
        options = wizard.resolve_options(args)
        wizard.validate_options(options)
        return options

    def demo_paths(self, options: wizard.WizardOptions) -> demo.DemoPaths:
        args = argparse.Namespace(
            account_id=options.account_id,
            app_dir=options.attach_dir or wizard.DEFAULT_ATTACH_DIR,
            token_file=options.token_file,
            accounts_file=options.accounts_file,
            pool_file=options.pool_file,
        )
        return demo.resolve_demo_paths(args)

    def require_claude_if_needed(self, options: wizard.WizardOptions) -> None:
        if options.skip_login:
            return
        if not shutil.which("claude"):
            raise wizard.WizardError("Claude CLI was not found on PATH.")

    def log_options(self, options: wizard.WizardOptions) -> None:
        token_path = Path(f"{options.token_file}_{options.account_id}").expanduser()
        self.set_metric("metric-account", "ACCOUNT", options.account_id, "isolated id")
        self.set_metric("metric-token", "TOKEN", token_path.name, "per-install file")
        self.set_metric("metric-model", "MODEL", self.args.model, "live checks")
        self.log_line(f"Account: {options.account_id}")
        self.log_line(f"Config:  {Path(options.config_dir).expanduser()}")
        self.log_line(f"Token:   {token_path}")
        self.log_line(f"App:     {Path(options.attach_dir).resolve() if options.attach_dir else 'not written'}")

    def fail_current(self, exc: Exception) -> None:
        self.set_run_state("FAILED")
        self.notify(str(exc), title="Setup failed", severity="error", timeout=10)
        self.log_line(f"FAILED: {type(exc).__name__}: {exc}")
        if self.current_step:
            self.update_step(self.current_step, "FAIL", type(exc).__name__)

    def update_step(self, key: str, status: str, detail: str) -> None:
        self.step_states[key] = status
        self.current_step = key if status == "RUN" else None
        widget = self.query_one(f"#step-{key}", Static)
        widget.update(self.step_text(STEP_LABELS[key], status, detail))
        widget.remove_class("running", "ok", "fail")
        if status == "RUN":
            widget.add_class("running")
        elif status == "OK":
            widget.add_class("ok")
        elif status == "FAIL":
            widget.add_class("fail")
        self.update_progress()

    def reset_steps(self) -> None:
        self.current_step = None
        for key in STEP_ORDER:
            self.step_states[key] = "WAIT"
            widget = self.query_one(f"#step-{key}", Static)
            widget.update(self.step_text(STEP_LABELS[key], "WAIT", STEP_DETAILS[key]))
            widget.remove_class("running", "ok", "fail")
        self.update_progress()

    def update_progress(self) -> None:
        complete = sum(1 for status in self.step_states.values() if status == "OK")
        self.query_one("#progress", ProgressBar).update(progress=complete)
        self.query_one("#progress-label", Static).update(
            f"{complete} of {len(STEP_ORDER)} complete",
        )

    @staticmethod
    def step_text(label: str, status: str, detail: str) -> str:
        status_label = STEP_STATUS[status]
        suffix = f"\n[dim]{escape(detail)}[/]" if detail else ""
        return f"[bold]{status_label:<8}[/] {escape(label)}{suffix}"

    @staticmethod
    def metric_text(label: str, value: str, detail: str) -> str:
        return f"[dim]{escape(label)}[/]\n[bold]{escape(value)}[/]\n[dim]{escape(detail)}[/]"

    def set_metric(self, widget_id: str, label: str, value: str, detail: str) -> None:
        self.query_one(f"#{widget_id}", Static).update(self.metric_text(label, value, detail))

    def set_run_state(self, value: str) -> None:
        self.query_one("#run-state", Static).update(f"[bold]{escape(value)}[/]")

    def log_line(self, text: str) -> None:
        self.query_one("#log", Log).write_line(f"{time.strftime('%H:%M:%S')}  {text}")

    def log_output(self, output: str) -> None:
        for line in output.splitlines():
            if line.strip():
                self.log_line(line)


def capture(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> CapturedResult:
    stream = io.StringIO()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        value = fn(*args, **kwargs)
    return CapturedResult(value=value, output=stream.getvalue())


if __name__ == "__main__":
    raise SystemExit(main())
