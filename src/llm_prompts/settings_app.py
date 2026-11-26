"""The interactive settings editor behind ``llm-prompts settings``."""

from __future__ import annotations

import copy
import re
from typing import Any, ClassVar, NamedTuple

import tomlkit
from textual.app import App, ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Label, Static, Switch
from tomlkit import TOMLDocument
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import Table

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
Repos = dict[str, int]


class Field(NamedTuple):
    """One string field of a ``[[tools]]`` or ``[[plugins]]`` entry."""

    key: str
    hint: str
    is_list: bool = False
    is_table: bool = False


ENTRY_FIELDS = {
    "tools": (
        Field("name", "name"),
        Field("source", "git URL or local path"),
        Field("ref", "latest release (default)"),
        Field("test", "test command (local path only)"),
    ),
    "plugins": (
        Field("name", "name"),
        Field("source", "git URL"),
        Field("ref", "default branch (default)"),
        Field("skills", "all skills (default)", is_list=True),
        Field("frontmatter_overrides", 'skill = {key = "value"}', is_table=True),
    ),
}
Row = tuple[int | None, dict[str, str]]
"""An entry's index in the loaded file (None for a new one) and its field texts."""


def _field_text(entry: dict[str, Any], field: Field) -> str:
    value = entry.get(field.key)
    if value is None:
        return ""
    if field.is_list and isinstance(value, list):
        return ", ".join(map(str, value))
    if field.is_table and isinstance(value, dict):
        table = tomlkit.inline_table()
        table.update(tomlkit.item(value).unwrap())
        return table.as_string()[1:-1].strip()
    return str(value)


def _rows(config: dict[str, Any], table: str) -> list[Row] | None:
    """Return the rows of ``table``'s entries, or None when it is not a list of tables."""
    entries = config.get(table, [])
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        return None
    return [
        (index, {field.key: _field_text(entry, field) for field in ENTRY_FIELDS[table]})
        for index, entry in enumerate(entries)
    ]


def _apply_rows(doc: TOMLDocument, table: str, rows: list[Row]) -> None:
    """Replace ``table``'s entries in ``doc`` with ``rows``, writing only changed fields."""
    # shortcut: an inline-table array (`tools = [{...}]`) is rewritten as [[tools]] tables
    # on save, losing its layout. Keep that form if users report writing it.
    old = list(doc.get(table, []))
    entries = tomlkit.aot()
    for origin, texts in rows:
        entry = tomlkit.table()
        if origin is not None and isinstance(old[origin], Table):
            entry = old[origin]
        elif origin is not None:
            entry.update(old[origin])
        for field in ENTRY_FIELDS[table]:
            text = texts[field.key].strip()
            if text == _field_text(entry, field):
                continue
            if not text:
                entry.pop(field.key, None)
            elif field.is_list:
                entry[field.key] = [s.strip() for s in text.split(",") if s.strip()]
            elif field.is_table:
                try:
                    entry[field.key] = tomlkit.parse(f"v = {{{text}}}")["v"].unwrap()
                except TOMLKitError:
                    raise ValueError(
                        f"{field.key} must be TOML key = value pairs"
                    ) from None
            else:
                entry[field.key] = text
        if origin is None:
            entry.add(tomlkit.nl())
        entries.append(entry)
    if entries:
        doc[table] = entries
    else:
        doc.pop(table, None)


def _describe_rows(table: str, before: list[Row], rows: list[Row]) -> list[str]:
    """Return lines naming ``table``'s entries and which of their fields changed, never a value."""
    names = [texts["name"].strip() or "(no name)" for _, texts in rows]
    lines = [f"[[{table}]] = {', '.join(names) or 'none'}"]
    for name, (origin, texts) in zip(names, rows, strict=True):
        if origin is None:
            lines.append(f"{name}: added")
            continue
        changed = [
            key for key, text in texts.items() if text.strip() != before[origin][1][key]
        ]
        if changed:
            lines.append(f"{name}: {', '.join(changed)} changed")
    return lines


class EntriesScreen(Screen[list[Row]]):
    """Edit, add, move and remove the entries of ``[[tools]]`` or ``[[plugins]]``."""

    BINDINGS: ClassVar[list[BindingType]] = [("escape", "done", "Done")]

    def __init__(self, table: str, rows: list[Row]) -> None:
        super().__init__()
        self._table = table
        self._rows = rows

    def compose(self) -> ComposeResult:
        fields = ENTRY_FIELDS[self._table]
        with VerticalScroll():
            yield Label(f"[[{self._table}]]", markup=False)
            for number, (_, texts) in enumerate(self._rows):
                with Horizontal(classes="entry"):
                    for field in fields:
                        yield Input(
                            texts[field.key],
                            placeholder=field.hint,
                            id=f"{self._table}-{number}-{field.key}",
                        )
                    yield Button("Up", id=f"up-{number}", disabled=not number)
                    yield Button("Remove", id=f"remove-{number}")
        with Horizontal(id="buttons"):
            yield Button("Add", id="add")
            yield Button("Done", id="done", variant="primary")
        yield Footer()

    def _read(self) -> None:
        for number, (_, texts) in enumerate(self._rows):
            for key in texts:
                texts[key] = self.query_one(
                    f"#{self._table}-{number}-{key}", Input
                ).value

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        self._read()
        action, _, number = (event.button.id or "").partition("-")
        if action == "done":
            self.action_done()
            return
        if action == "add":
            self._rows.append(
                (None, {field.key: "" for field in ENTRY_FIELDS[self._table]})
            )
        elif action == "up":
            index = int(number)
            self._rows[index - 1], self._rows[index] = (
                self._rows[index],
                self._rows[index - 1],
            )
        elif action == "remove":
            del self._rows[int(number)]
        await self.recompose()

    def action_done(self) -> None:
        self._read()
        self.dismiss(self._rows)


def _doc_table(doc: dict[str, Any], name: str) -> dict[str, Any]:
    """Return the table called ``name`` in ``doc``, adding it when missing.

    Raises:
        TypeError: When ``name`` is not a table.
    """
    if name not in doc:
        doc[name] = tomlkit.table()
    table = doc[name]
    if not isinstance(table, dict):
        raise TypeError(f"[{name}] must be a table")
    return table


def _edited(
    loaded: LoadedConfig,
    edits: dict[Setting, Value],
    repos: Repos | None,
    entries: dict[str, list[Row]],
) -> TOMLDocument:
    """Return a copy of the loaded document with each edit applied.

    A setting edited to None is removed. ``repos``, when given, replaces
    ``reviews.repos``. ``entries`` replaces the rows of each table it names.

    Raises:
        TypeError: When an edited table is not a table.
    """
    doc = tomlkit.parse(loaded.text or "")
    for setting, new in edits.items():
        table = _doc_table(doc, setting.table)
        if new is None:
            table.pop(setting.key, None)
        else:
            table[setting.key] = new
    if repos is not None:
        reviews = _doc_table(doc, "reviews")
        if not repos:
            reviews.pop("repos", None)
        else:
            limits = _doc_table(reviews, "repos")
            for scope in [scope for scope in limits if scope not in repos]:
                del limits[scope]
            for scope, limit in repos.items():
                if limits.get(scope) != limit:
                    limits[scope] = limit
    for name, rows in entries.items():
        _apply_rows(doc, name, rows)
    return doc


def _repos_text(config: dict[str, Any]) -> str:
    repos = _table(config, "reviews").get("repos")
    if not isinstance(repos, dict):
        return ""
    return ", ".join(f"{scope}={limit}" for scope, limit in repos.items())


def _parse_repos(text: str) -> Repos:
    """Return the scope=number pairs in ``text``.

    Raises:
        ValueError: When a pair has no scope or its limit is not a whole number.
    """
    repos: Repos = {}
    for pair in filter(None, (part.strip() for part in text.split(","))):
        scope, _, limit = pair.rpartition("=")
        try:
            if not scope.strip():
                raise ValueError
            repos[scope.strip()] = int(limit)
        except ValueError:
            raise ValueError("reviews.repos must be scope=number pairs") from None
    return repos


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
        self, loaded: LoadedConfig, changes: list[str], doc: TOMLDocument
    ) -> None:
        super().__init__()
        self._loaded = loaded
        self._changes = changes
        self._doc = doc
        self._errors = _problems_without_values(doc.unwrap())

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(
                "\n".join(self._changes) or "No changes.", id="changes", markup=False
            )
            yield Static("\n".join(self._errors), id="errors", markup=False)
        with Horizontal(id="buttons"):
            yield Button(
                "Save",
                id="save",
                variant="primary",
                disabled=not self._changes or bool(self._errors),
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
    #reviews-repos { width: 1fr; }
    .entry { height: auto; }
    .entry Input { width: 1fr; }
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
        config = loaded.doc.unwrap()
        self._initial_rows = {table: _rows(config, table) for table in ENTRY_FIELDS}
        self._rows = copy.deepcopy(self._initial_rows)
        self.changed_tables: set[str] = set()

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
            with Horizontal(classes="row"):
                yield Label("reviews.repos")
                yield Input(
                    _repos_text(config),
                    placeholder="owner/repo=number, ...",
                    id="reviews-repos",
                )
            yield Static(id="input-errors", markup=False)
        with Horizontal(id="buttons"):
            for table in ENTRY_FIELDS:
                yield Button(
                    table.capitalize(),
                    id=table,
                    disabled=self._initial_rows[table] is None,
                )
            yield Button("Review", id="review", variant="primary")
            yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self._initial = self._widget_values()
        self._initial_repos = self.query_one("#reviews-repos", Input).value

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
            text = self.query_one("#reviews-repos", Input).value
            repos = None if text == self._initial_repos else _parse_repos(text)
            entries = {
                table: rows
                for table, rows in self._rows.items()
                if rows is not None and rows != self._initial_rows[table]
            }
            doc = _edited(self._loaded, edits, repos, entries)
        except (TypeError, ValueError) as error:
            errors.update(str(error))
            return
        errors.update("")
        changes = [_describe(setting, value) for setting, value in edits.items()]
        if repos is not None:
            shown = ", ".join(f"{scope}={limit}" for scope, limit in repos.items())
            changes.append(f"reviews.repos = {shown or 'none'}")
        for table, rows in entries.items():
            changes += _describe_rows(table, self._initial_rows[table] or [], rows)
        self.changed_tables = set(entries)
        self.push_screen(ReviewScreen(self._loaded, changes, doc))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ENTRY_FIELDS:
            table = event.button.id
            self.push_screen(
                EntriesScreen(table, copy.deepcopy(self._rows[table] or [])),
                lambda rows: self._rows.__setitem__(table, rows),
            )
        elif event.button.id == "review":
            self.action_review()
        elif event.button.id == "quit":
            self.exit(False)
