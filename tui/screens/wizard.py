from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from textual.containers import Vertical, Center

from tui.config import has_remotes, has_targets


class WizardScreen(Screen):

    def compose(self) -> ComposeResult:
        yield Header()
        with Center():
            with Vertical(id="wizard"):
                yield Static(
                    "[bold]Welcome to gniza Backup Manager![/bold]\n\n"
                    "This wizard will help you set up your first backup:\n\n"
                    "  1. Configure a backup destination (remote)\n"
                    "  2. Define what to back up (target)\n"
                    "  3. Optionally run your first backup\n",
                    id="wizard-welcome",
                    markup=True,
                )
                if not has_remotes():
                    yield Button("Step 1: Add Remote", variant="primary", id="wiz-remote")
                else:
                    yield Static("[green]Remote configured.[/green]", markup=True)
                if not has_targets():
                    yield Button("Step 2: Add Target", variant="primary", id="wiz-target")
                else:
                    yield Static("[green]Target configured.[/green]", markup=True)
                yield Button("Continue to Main Menu", id="wiz-continue")
                yield Button("Skip Setup", id="wiz-skip")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "wiz-remote":
            self.app.push_screen("remote_edit", callback=self._check_progress)
        elif event.button.id == "wiz-target":
            self.app.push_screen("target_edit", callback=self._check_progress)
        elif event.button.id in ("wiz-continue", "wiz-skip"):
            self.app.switch_screen("main")

    def _check_progress(self, result) -> None:
        if has_remotes() and has_targets():
            self.app.switch_screen("main")
