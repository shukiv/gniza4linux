import subprocess
from pathlib import Path

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from tui.widgets.header import GnizaHeader as Header  # noqa: F811
from textual.containers import Vertical, Horizontal, Center
from textual import work

from lib.config import has_remotes, has_targets, list_conf_dir
from tui.jobs import job_manager


def _has_schedules():
    return len(list_conf_dir("schedules.d")) > 0


def _get_ssh_keys():
    ssh_dir = Path.home() / ".ssh"
    keys = []
    if ssh_dir.is_dir():
        for pub in sorted(ssh_dir.glob("*.pub")):
            try:
                content = pub.read_text().strip()
                keys.append({"name": pub.stem, "path": str(pub), "content": content})
            except OSError:
                pass
    return keys


class WizardScreen(Screen):

    BINDINGS = [("escape", "skip_wizard", "Skip Wizard")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Center():
            with Vertical(id="wizard"):
                yield Static("", id="wizard-welcome", markup=True)
                yield Vertical(id="wizard-body")
                with Horizontal(id="wizard-nav"):
                    yield Button("← Back", id="wiz-back")
                    yield Button("Next →", variant="primary", id="wiz-next")
                    yield Button("Skip Wizard", id="wiz-skip")
        yield Footer()

    def on_mount(self) -> None:
        self._step = self._auto_step()
        self._refresh_step()

    def _auto_step(self) -> int:
        if not has_remotes():
            return 0
        if not has_targets():
            return 2
        if not _has_schedules():
            return 3
        return 4

    def _refresh_step(self) -> None:
        welcome = self.query_one("#wizard-welcome", Static)
        body = self.query_one("#wizard-body", Vertical)
        back_btn = self.query_one("#wiz-back", Button)
        next_btn = self.query_one("#wiz-next", Button)

        body.remove_children()
        step = self._step

        welcome.update(
            f"[bold]Setup Wizard[/bold]  —  Step {step + 1} of 5\n"
        )

        back_btn.display = step > 0
        next_btn.display = step < 4

        if step == 0:
            self._render_prepare(body)
            next_btn.label = "Next →"
        elif step == 1:
            self._render_destination(body)
            next_btn.label = "Next →" if has_remotes() else "Skip →"
        elif step == 2:
            self._render_source(body)
            next_btn.label = "Next →" if has_targets() else "Skip →"
        elif step == 3:
            self._render_schedule(body)
            next_btn.label = "Next →" if _has_schedules() else "Skip →"
        elif step == 4:
            self._render_done(body)
            next_btn.display = False

    def _render_prepare(self, body: Vertical) -> None:
        keys = _get_ssh_keys()
        body.mount(Static(
            "[bold]Prepare: SSH Keys[/bold]\n\n"
            "If backing up to/from a remote server via SSH,\n"
            "you need an SSH key pair.\n",
            markup=True,
        ))
        if keys:
            for k in keys:
                body.mount(Static(
                    f"  [green]●[/green] {k['name']}  ({k['path']})\n"
                    f"    [dim]{k['content'][:72]}...[/dim]" if len(k['content']) > 72
                    else f"  [green]●[/green] {k['name']}  ({k['path']})\n"
                    f"    [dim]{k['content']}[/dim]",
                    markup=True,
                ))
            body.mount(Static(""))
        else:
            body.mount(Static(
                "  [yellow]No SSH keys found.[/yellow]\n",
                markup=True,
            ))
        body.mount(Button("Generate SSH Key", id="wiz-keygen"))
        body.mount(Static(
            "\n[dim]Copy the public key to each remote server:\n"
            "  ssh-copy-id -i ~/.ssh/id_ed25519_gniza user@host[/dim]",
            markup=True,
        ))

    def _render_destination(self, body: Vertical) -> None:
        remotes = list_conf_dir("remotes.d")
        body.mount(Static(
            "[bold]Step 2: Add a Destination[/bold]\n\n"
            "Where should backups be stored?\n",
            markup=True,
        ))
        if remotes:
            for r in remotes:
                body.mount(Static(f"  [green]✓[/green] {r}", markup=True))
            body.mount(Static(""))
        body.mount(Button("Add Destination", variant="primary", id="wiz-add-remote"))

    def _render_source(self, body: Vertical) -> None:
        targets = list_conf_dir("targets.d")
        body.mount(Static(
            "[bold]Step 3: Add a Source[/bold]\n\n"
            "What should be backed up?\n",
            markup=True,
        ))
        if targets:
            for t in targets:
                body.mount(Static(f"  [green]✓[/green] {t}", markup=True))
            body.mount(Static(""))
        body.mount(Button("Add Source", variant="primary", id="wiz-add-target"))

    def _render_schedule(self, body: Vertical) -> None:
        schedules = list_conf_dir("schedules.d")
        body.mount(Static(
            "[bold]Step 4: Create a Schedule[/bold]\n\n"
            "When should backups run?\n",
            markup=True,
        ))
        if schedules:
            for s in schedules:
                body.mount(Static(f"  [green]✓[/green] {s}", markup=True))
            body.mount(Static(""))
        body.mount(Button("Add Schedule", variant="primary", id="wiz-add-schedule"))

    def _render_done(self, body: Vertical) -> None:
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        schedules = list_conf_dir("schedules.d")
        body.mount(Static(
            "[bold]Setup Complete![/bold]\n\n"
            f"  Destinations: [green]{len(remotes)}[/green]\n"
            f"  Sources:      [green]{len(targets)}[/green]\n"
            f"  Schedules:    [green]{len(schedules)}[/green]\n",
            markup=True,
        ))
        if targets and remotes:
            body.mount(Button("Run First Backup", variant="primary", id="wiz-run-backup"))
        body.mount(Button("Go to Main Menu", variant="default", id="wiz-finish"))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "wiz-back":
            if self._step > 0:
                self._step -= 1
                self._refresh_step()
        elif bid == "wiz-next":
            if self._step < 4:
                self._step += 1
                self._refresh_step()
        elif bid == "wiz-skip":
            self.app.switch_screen("main")
        elif bid == "wiz-keygen":
            self._generate_key()
        elif bid == "wiz-add-remote":
            self.app.push_screen("remote_edit", callback=self._on_sub_return)
        elif bid == "wiz-add-target":
            self.app.push_screen("target_edit", callback=self._on_sub_return)
        elif bid == "wiz-add-schedule":
            self.app.push_screen("schedule_edit", callback=self._on_sub_return)
        elif bid == "wiz-run-backup":
            self._run_first_backup()
        elif bid == "wiz-finish":
            self.app.switch_screen("main")

    def _on_sub_return(self, result) -> None:
        self._refresh_step()

    @work
    async def _generate_key(self) -> None:
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        key_path = ssh_dir / "id_ed25519_gniza"
        if key_path.exists():
            self.notify("Key already exists: id_ed25519_gniza")
            self._refresh_step()
            return
        try:
            subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", "", "-C", "gniza-backup"],
                check=True, capture_output=True, text=True,
            )
            self.notify("SSH key generated: id_ed25519_gniza")
        except subprocess.CalledProcessError as e:
            self.notify(f"ssh-keygen failed: {e.stderr.strip()}", severity="error")
        self._refresh_step()

    def _run_first_backup(self) -> None:
        targets = list_conf_dir("targets.d")
        remotes = list_conf_dir("remotes.d")
        schedules = list_conf_dir("schedules.d")
        if schedules:
            args = ["scheduled-run", f"--schedule={schedules[0]}"]
            label = f"First backup: {schedules[0]}"
        else:
            args = ["backup", f"--source={targets[0]}", f"--destination={remotes[0]}"]
            label = f"First backup: {targets[0]} -> {remotes[0]}"
        job = job_manager.create_job("backup", label)
        job_manager.start_job(self.app, job, *args)
        self.notify("First backup started!")
        self.app.switch_screen("running_tasks")

    def action_skip_wizard(self) -> None:
        self.app.switch_screen("main")
