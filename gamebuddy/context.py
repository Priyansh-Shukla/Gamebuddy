"""Load game-context: meta, progression DAG, and entity files.

A game context is the developer-authored knowledge package shipped per game.
It lives under games/<game_id>/ and contains:

  meta.md             frontmatter + body; game-level metadata
  progression.yaml    nodes + requires/suggests edges
  entities/**/*.md    per-entity frontmatter (node_id, type, gates) + body

Loading is purely deterministic. No network, no API calls.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from gamebuddy.schemas import NodeId


class FrontmatterError(ValueError):
    pass


def _split_frontmatter(text: str) -> tuple[dict, str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return {}, text
    rest = text[len("---\n"):]
    closing = rest.find("\n---")
    if closing == -1:
        raise FrontmatterError("opening --- without closing ---")
    fm_text = rest[:closing]
    body = rest[closing + len("\n---"):].lstrip("\n")
    data = yaml.safe_load(fm_text) or {}
    if not isinstance(data, dict):
        raise FrontmatterError(
            f"frontmatter must be a mapping, got {type(data).__name__}"
        )
    return data, body


@dataclass
class MetaInfo:
    game_id: str
    title: str
    schema_version: int
    save_path: str | None = None
    parser: str | None = None
    sources: list[str] = field(default_factory=list)
    body: str = ""


@dataclass
class Entity:
    node_id: NodeId
    type: str
    gates: set[NodeId]
    body: str
    path: Path


@dataclass
class ProgressionNode:
    node_id: NodeId
    type: str


@dataclass
class ProgressionDAG:
    nodes: dict[NodeId, ProgressionNode]
    requires: dict[NodeId, set[NodeId]]
    suggests: dict[NodeId, set[NodeId]]

    def ancestors(self, node: NodeId) -> set[NodeId]:
        # 'suggests' is narrative-only per DESIGN.md and excluded from
        # safety-relevant ancestor computation.
        if node not in self.nodes:
            raise KeyError(f"unknown node: {node}")
        seen: set[NodeId] = set()
        stack = list(self.requires.get(node, ()))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(self.requires.get(n, ()))
        return seen


@dataclass
class GameContext:
    meta: MetaInfo
    dag: ProgressionDAG
    entities: list[Entity]


def _load_meta(meta_path: Path) -> MetaInfo:
    fm, body = _split_frontmatter(meta_path.read_text(encoding="utf-8"))
    required = ("game_id", "title", "schema_version")
    missing = [k for k in required if k not in fm]
    if missing:
        raise FrontmatterError(f"{meta_path}: missing required keys: {missing}")
    return MetaInfo(
        game_id=fm["game_id"],
        title=fm["title"],
        schema_version=int(fm["schema_version"]),
        save_path=fm.get("save_path"),
        parser=fm.get("parser"),
        sources=list(fm.get("sources", []) or []),
        body=body,
    )


def _load_progression(prog_path: Path) -> ProgressionDAG:
    data = yaml.safe_load(prog_path.read_text(encoding="utf-8")) or {}
    raw_nodes = data.get("nodes", []) or []
    nodes: dict[NodeId, ProgressionNode] = {}
    requires: dict[NodeId, set[NodeId]] = defaultdict(set)
    suggests: dict[NodeId, set[NodeId]] = defaultdict(set)
    for raw in raw_nodes:
        node_id = raw["id"]
        if node_id in nodes:
            raise ValueError(f"{prog_path}: duplicate node id {node_id!r}")
        nodes[node_id] = ProgressionNode(node_id=node_id, type=raw["type"])
        for r in raw.get("requires", []) or []:
            requires[node_id].add(r)
        for s in raw.get("suggests", []) or []:
            suggests[node_id].add(s)
    for src, preds in list(requires.items()) + list(suggests.items()):
        for p in preds:
            if p not in nodes:
                raise ValueError(
                    f"{prog_path}: edge from {src!r} references unknown node {p!r}"
                )
    return ProgressionDAG(
        nodes=nodes,
        requires=dict(requires),
        suggests=dict(suggests),
    )


def _load_entity(entity_path: Path) -> Entity:
    fm, body = _split_frontmatter(entity_path.read_text(encoding="utf-8"))
    if "node_id" not in fm or "type" not in fm:
        raise FrontmatterError(
            f"{entity_path}: entity must declare node_id and type"
        )
    return Entity(
        node_id=fm["node_id"],
        type=fm["type"],
        gates=set(fm.get("gates", []) or []),
        body=body,
        path=entity_path,
    )


def load_game_context(games_dir: Path, game_id: str) -> GameContext:
    base = games_dir / game_id
    if not base.is_dir():
        raise FileNotFoundError(f"no game-context directory: {base}")
    meta = _load_meta(base / "meta.md")
    if meta.game_id != game_id:
        raise ValueError(
            f"meta.game_id={meta.game_id!r} does not match directory name {game_id!r}"
        )
    dag = _load_progression(base / "progression.yaml")
    entities_dir = base / "entities"
    entities: list[Entity] = []
    if entities_dir.is_dir():
        for p in sorted(entities_dir.rglob("*.md")):
            entities.append(_load_entity(p))
    for e in entities:
        if e.node_id not in dag.nodes:
            raise ValueError(
                f"{e.path}: node_id {e.node_id!r} not in progression.yaml"
            )
        unknown = e.gates - dag.nodes.keys()
        if unknown:
            raise ValueError(
                f"{e.path}: gates reference unknown nodes: {sorted(unknown)}"
            )
    return GameContext(meta=meta, dag=dag, entities=entities)
