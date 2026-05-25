"""Provider abstraction: anything that produces Observations.

SaveFileProvider (later) parses a save file once per invocation;
ScreenshotProvider (v2+) captures images; ManualProvider takes a CLI input.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from gamebuddy.schemas import Observation


class Provider(ABC):
    @abstractmethod
    def collect(self) -> list[Observation]: ...
