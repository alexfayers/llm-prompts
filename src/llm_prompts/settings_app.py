"""The interactive settings editor behind ``llm-prompts settings``."""

from __future__ import annotations

import re
from typing import Any, ClassVar

import tomlkit
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static, Switch
from tomlkit import TOMLDocument

from .config_edit import LoadedConfig, save_doc
from .exit_reason import ExitReason
from .settings import SETTINGS, Setting, config_problems
from .setup import config_errors, config_path


def _widget_id(setting: Setting) -> str:
    return f"{setting.table}-{setting.key}"


def _table(config: dict[str, Any], name: str) -> dict[str, Any]:
    table = config.get(name)
    return table if isinstance(table, dict) else {}


Value = bool | int | None


def _edited(loaded: LoadedConfig, edits: dict[Setting, Value]) -> TOMLDocument:
    """Return a copy of the loaded document with each edited setting set, or removed when None.

    Raises:
        TypeError: When a setting's table is not a table.
    """
    doc = tomlkit.parse(loaded.text or "")
    for setting, new in edits.items():
        if setting.table not in doc:
            doc[setting.table] = tomlkit.table()
        table = doc[setting.table]
        if not isinstance(table, dict):
            raise TypeError(f"[{setting.table}] must be a table")
        if new is None:
            table.pop(setting.key, None)
        else:
            table[setting.key] = new
    return doc


def _describe(setting: Setting, value: Value) -> str:
    shown = setting.default if value is None else value
    text = str(shown).lower() if isinstance(shown, bool) else str(shown)
    return f"{setting.table}.{setting.key} = {text}" + (
        " (default)" if value is None else ""
    )


_ENTRY_FIELDS = {
    "frontmatter_overrides": "frontmatter_overrides",
    "source": "source",
    "path": "source",
    "name": "name",
}


def _entry_problems(table: str, entries: Any) -> list[str]:
    """Return the problems in an array of tables, naming each entry and field but never a value."""
    if not isinstance(entries, list):
        return [f"[[{table}]] must be a list of tables"]
    baseline = set(config_errors({"tools": []}))
    problems: list[str] = []
    for number, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            problems.append(f"[[{table}]] entry {number} must be a table")
            continue
        alone = (
            {"tools": [entry]} if table == "tools" else {"tools": [], table: [entry]}
        )
        for error in config_errors(alone):
            if error in baseline:
                continue
            head = re.sub(r"^\[[^\]]*\] ", "", error).partition(": ")[0].lower()
            field = next((f for word, f in _ENTRY_FIELDS.items() if word in head), None)
            problem = f"[[{table}]] entry {number}" + (
                f": {field} is invalid" if field else " is invalid"
            )
            if problem not in problems:
                problems.append(problem)
    return problems


def _problems_without_values(config: dict[str, Any]) -> list[str]:
    """Return the config's problems, naming each invalid field and rule but never a value."""
    tools = config.get("tools", [])
    problems = [] if tools else config_errors({})
    problems += _entry_problems("tools", tools) + _entry_problems(
        "plugins", config.get("plugins", [])
    )
    entry_errors = set(config_errors(config))
    for problem in config_problems(config):
        if problem in entry_errors:
            continue
        rule, got, _ = problem.partition(", got ")
        if problem.startswith("["):
            problems.append(problem)
        elif got:
            problems.append(rule)
        else:
            problems.append(f"{problem.partition(' ')[0]} is invalid")
    return problems


class ReviewScreen(Screen[None]):
    """Show the edited settings and save them, unless the edited config has errors."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "app.pop_screen", "Back"),
        ("ctrl+s", "save", "Save"),
    ]

    def __init__(
        self, loaded: LoadedConfig, edits: dict[Setting, Value], doc: TOMLDocument
    ) -> None:
        super().__init__()
        self._loaded = loaded
        self._edits = edits
        self._doc = doc
        self._errors = _problems_without_values(doc.unwrap())

    def compose(self) -> ComposeResult:
        changes = [_describe(setting, value) for setting, value in self._edits.items()]
        with VerticalScroll():
            yield Static(
                "\n".join(changes) or "No changes.", id="changes", markup=False
            )
            yield Static("\n".join(self._errors), id="errors", markup=False)
        with Horizontal(id="buttons"):
            yield Button(
                "Save",
                id="save",
                variant="primary",
                disabled=not changes or bool(self._errors),
            )
            yield Button("Back", id="back")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back":
            self.app.pop_screen()
        else:
            self.action_save()

    def action_save(self) -> None:
        if self.query_one("#save", Button).disabled:
            return
        try:
            save_doc(LoadedConfig(self._doc, self._loaded.text))
        except ExitReason as error:
            self.query_one("#errors", Static).update(str(error.code))
            return
        except OSError as error:
            self.query_one("#errors", Static).update(
                f"Could not save {config_path()}: {error.strerror or type(error).__name__}"
            )
            return
        self.app.exit(True)


class SettingsApp(App[bool]):
    """Edit the config file's settings, then review the change and save it."""

    TITLE = "llm-prompts settings"
    CSS = """
    .row { height: auto; }
    .row Label { width: 28; padding: 1 0; }
    .row Input { width: 16; }
    #errors, #input-errors { color: $error; }
    #buttons { height: auto; }
    """
    BINDINGS: ClassVar[list[BindingType]] = [
        ("escape", "quit", "Quit"),
        ("ctrl+s", "review", "Review"),
    ]

    def __init__(self, loaded: LoadedConfig) -> None:
        super().__init__()
        self._loaded = loaded

    def compose(self) -> ComposeResult:
        config = self._loaded.doc.unwrap()
        with VerticalScroll():
            yield Label(f"Config: {config_path()}", markup=False)
            for setting in SETTINGS:
                value = _table(config, setting.table).get(setting.key)
                with Horizontal(classes="row"):
                    yield Label(f"{setting.table}.{setting.key}")
                    if isinstance(setting.default, bool):
                        yield Switch(
                            value=setting.default if value is None else bool(value),
                            id=_widget_id(setting),
                        )
                    else:
                        yield Input(
                            "" if value is None else str(value),
                            placeholder=f"{setting.default} (default)",
                            type="integer",
                            id=_widget_id(setting),
                        )
            yield Static(id="input-errors", markup=False)
        with Horizontal(id="buttons"):
            yield Button("Review", id="review", variant="primary")
            yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self._initial = self._widget_values()

    def _widget_values(self) -> dict[Setting, bool | str]:
        values: dict[Setting, bool | str] = {}
        for setting in SETTINGS:
            widget = self.query_one(f"#{_widget_id(setting)}")
            if isinstance(widget, (Switch, Input)):
                values[setting] = widget.value
        return values

    def _edits(self) -> dict[Setting, Value]:
        """Return the settings whose widgets changed, each with its new value.

        Raises:
            ValueError: When an edited number field holds text that is not an integer.
        """
        edits: dict[Setting, Value] = {}
        for setting, value in self._widget_values().items():
            if value == self._initial[setting]:
                continue
            if isinstance(value, bool):
                edits[setting] = value
                continue
            text = value.strip()
            try:
                edits[setting] = int(text) if text else None
            except ValueError:
                raise ValueError(
                    f"{setting.table}.{setting.key} must be a whole number"
                ) from None
        return edits

    def action_review(self) -> None:
        errors = self.query_one("#input-errors", Static)
        try:
            edits = self._edits()
            doc = _edited(self._loaded, edits)
        except (TypeError, ValueError) as error:
            errors.update(str(error))
            return
        errors.update("")
        self.push_screen(ReviewScreen(self._loaded, edits, doc))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "review":
            self.action_review()
        elif event.button.id == "quit":
            self.exit(False)
