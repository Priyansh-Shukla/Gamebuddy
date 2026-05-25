"""Onboarding: draft a game-context for <game_id> via a tool-using LLM.

The spoiler rule does not apply at authoring time — there's no player to
spoil — so web_search and web_fetch are explicitly allowed here. Output is
a starting draft for the developer to review, edit, and commit; not a
finished artifact.

Tools given to the model:
  - web_search_20260209  (server; dynamic filtering built in on Opus 4.7)
  - web_fetch_20260209   (server; dynamic filtering built in on Opus 4.7)
  - write_file           (custom; sandboxed to games/<game_id>/)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_ROUNDS = 50

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": (
        "Write a file into the game-context directory. `path` is relative to "
        "games/<game_id>/ — do not include the game-context root or any "
        "absolute path. Creates parent directories as needed. Overwrites "
        "existing files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "Relative path, e.g. 'meta.md' or "
                    "'entities/bosses/genichiro.md'."
                ),
            },
            "content": {
                "type": "string",
                "description": "Full file content including any frontmatter.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """You are the GameBuddy onboarding author. Research a singleplayer game using web tools, then produce a complete game-context package by writing files into the game-context directory.

# Output shape

Write these files via the write_file tool. All paths are relative to the game-context root — never include the root or any absolute path.

## meta.md
YAML frontmatter, then a 2-4 paragraph game overview as the body. Required frontmatter keys:
  game_id: <slug, must match the game id you were given>
  title: <human-readable title>
  schema_version: 1
  sources:
    - <URL>
    - <URL>
Optional: save_path, parser.

## progression.yaml
A list of nodes with optional `requires` / `suggests` edges. Example:
  nodes:
    - id: ashina_outskirts
      type: area
    - id: chained_ogre
      type: boss
      requires: [ashina_outskirts]
    - id: ashina_castle_gate
      type: area
      requires: [chained_ogre]

Types: `area`, `boss`, `item`, `skill`, `story_beat`, `ending`.
- `requires` = hard prerequisite (you cannot reach this node without those)
- `suggests` = narrative ordering (normally encountered after, but not gated)
Use `suggests` for soft ordering; reserve `requires` for true blockers.

## entities/<category>/<node_id>.md
One file per node. Frontmatter, then 2-5 paragraphs of body:
  ---
  node_id: <must match a node id in progression.yaml>
  type: <same type as in progression.yaml>
  gates: [<node ids that must be observed before this content is safe to show>]
  ---
  <body>

`<category>` is a directory like `bosses/`, `areas/`, `items/`, `endings/`. Keep it consistent with the node type.

# Granularity

Target ~50 nodes total. Cover: major bosses, named areas, key items, key story beats, endings. Skip: minor checkpoints, common enemies, incidental loot, every sub-area. Bias toward fewer, larger nodes — node IDs need to be memorable for manual logging.

# Gates contract

`gates` is the set of node IDs that must be in the player's observed boundary before this entity's content is shown to the player. The filter is a plain subset check: an entity is shown iff `gates ⊆ observed`.

Common gate patterns:
- Area entity → gated on the area's own node (content shows once area is reached)
- Boss entity → gated on a predecessor area or the predecessor boss
- Item entity → gated on the area or boss where it's found
- Ending entity → gated tightly on the ending's own node id (do not gate endings on predecessors)

# Anti-spoiler rules for entity bodies

Each entity body is shown only when its gates are satisfied — but the *content* of the body is your responsibility. Within each entity body:
- Reference only events, characters, and items that are part of THIS entity or its predecessors.
- Do not foreshadow future content (no "this will become important later").
- Include trivia and lore inline where it fits naturally. Each trivia note must stand on its own — do not connect lore across entities to imply relationships the player hasn't encountered.
- Do not write phrases like "you may have missed X" — implying optional content the player skipped is a meta-spoiler.

# Workflow

1. Use `web_search` to find authoritative sources for the game (community wiki, walkthrough).
2. Use `web_fetch` to read the relevant pages.
3. Decide the ~50 nodes.
4. Write `progression.yaml`.
5. Write `meta.md`.
6. Write each entity file under `entities/<category>/<node_id>.md`.
7. End your turn when the draft is complete — do not call write_file again after that. Briefly summarize what you wrote and any judgment calls the developer should review."""


class OnboardError(RuntimeError):
    pass


def _validate_relative_path(rel: str) -> Path:
    if not rel:
        raise OnboardError("path must not be empty")
    # POSIX-absolute (`/foo`) or Windows-rooted (`\foo`) — Path.is_absolute()
    # returns False for `/foo` on Windows since there's no drive, so check the
    # leading character explicitly before the cross-platform checks below.
    if rel.startswith(("/", "\\")):
        raise OnboardError(f"path must be relative, not absolute: {rel!r}")
    p = Path(rel)
    if p.is_absolute():
        raise OnboardError(f"path must be relative, not absolute: {rel!r}")
    if ".." in p.parts:
        raise OnboardError(f"path must not contain '..': {rel!r}")
    if p.drive:
        raise OnboardError(f"path must not contain a drive component: {rel!r}")
    return p


class Onboarder:
    """Drives the agentic loop. Streams text output via `output` callable."""

    def __init__(
        self,
        *,
        game_id: str,
        target_dir: Path,
        client=None,
        model: str | None = None,
        output: Callable[[str], None] | None = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
    ) -> None:
        self._game_id = game_id
        self._target = target_dir
        self._model = model or os.environ.get("GAMEBUDDY_MODEL", DEFAULT_MODEL)
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self._client = client
        self._output = output or (lambda _msg: None)
        self._max_rounds = max_rounds
        self.files_written: list[Path] = []

    def run(self) -> list[Path]:
        tools = [
            {"type": "web_search_20260209", "name": "web_search"},
            {"type": "web_fetch_20260209", "name": "web_fetch"},
            WRITE_FILE_TOOL,
        ]
        messages = [
            {
                "role": "user",
                "content": (
                    f"Draft a complete game-context for the game with id `{self._game_id}`. "
                    f"Research it via web_search and web_fetch, then write the files via "
                    f"write_file. Target ~50 nodes. End your turn when the draft is complete."
                ),
            }
        ]

        for _ in range(self._max_rounds):
            response = self._one_turn(messages, tools)
            messages.append({"role": "assistant", "content": response.content})
            self._report_tool_calls(response.content)

            stop = getattr(response, "stop_reason", None)
            if stop == "end_turn":
                return self.files_written
            if stop == "pause_turn":
                continue  # server-side tool iteration limit — resend to resume

            tool_results = self._handle_custom_tools(response.content)
            if tool_results:
                messages.append({"role": "user", "content": tool_results})
                continue
            if stop == "tool_use":
                continue  # only server tools were used this turn
            raise OnboardError(f"unexpected stop_reason: {stop!r}")

        raise OnboardError(
            f"hit max rounds ({self._max_rounds}) without completing the draft"
        )

    def _one_turn(self, messages, tools):
        with self._client.messages.stream(
            model=self._model,
            max_tokens=64000,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                self._output(text)
            return stream.get_final_message()

    def _report_tool_calls(self, content) -> None:
        for block in content:
            btype = getattr(block, "type", None)
            if btype == "tool_use":
                name = getattr(block, "name", "?")
                inp = getattr(block, "input", {}) or {}
                if name == "write_file":
                    self._output(f"\n  + write_file {inp.get('path', '?')}\n")
                elif name == "web_search":
                    q = inp.get("query", "?")
                    self._output(f"\n  > web_search {q!r}\n")
                elif name == "web_fetch":
                    url = inp.get("url", "?")
                    self._output(f"\n  > web_fetch {url}\n")

    def _handle_custom_tools(self, content) -> list[dict]:
        results: list[dict] = []
        for block in content:
            if getattr(block, "type", None) != "tool_use":
                continue
            if getattr(block, "name", None) != "write_file":
                continue  # server tools are handled by Anthropic
            try:
                written = self._handle_write(block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Wrote {written.relative_to(self._target)}",
                })
            except OnboardError as exc:
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                })
        return results

    def _handle_write(self, input_data: dict) -> Path:
        path_arg = input_data.get("path")
        content_arg = input_data.get("content")
        if not isinstance(path_arg, str) or not isinstance(content_arg, str):
            raise OnboardError("write_file requires string `path` and `content`")
        rel = _validate_relative_path(path_arg)
        full = self._target / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content_arg, encoding="utf-8", newline="\n")
        self.files_written.append(full)
        return full
