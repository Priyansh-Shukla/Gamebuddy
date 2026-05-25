"""Manual user observations entered via `gamebuddy log`."""
from __future__ import annotations

from datetime import datetime, timezone

from gamebuddy.context import ProgressionDAG
from gamebuddy.providers import Provider
from gamebuddy.schemas import Observation


class ManualProvider(Provider):
    """Wraps a single CLI log input.

    If the input string matches a known node id in the DAG, the resulting
    Observation carries that node_id and so advances `observed` when
    applied. Otherwise it's a free-text annotation (node_id=None).
    """

    def __init__(
        self,
        dag: ProgressionDAG,
        input_text: str,
        *,
        now: datetime | None = None,
    ) -> None:
        self._dag = dag
        self._input = input_text
        self._now = now or datetime.now(tz=timezone.utc)

    def collect(self) -> list[Observation]:
        text = self._input.strip()
        node_id = text if text in self._dag.nodes else None
        return [
            Observation(
                timestamp=self._now,
                source="manual",
                node_id=node_id,
                payload={"text": text},
            )
        ]
