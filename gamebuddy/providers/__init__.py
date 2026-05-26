"""Provider abstraction: anything that produces Observations.

Save-file providers (e.g. `SekiroSaveProvider`) parse a save file once
per invocation; `ScreenshotProvider` (v2+) will capture images;
`ManualProvider` takes a CLI input.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from gamebuddy.schemas import Observation


class Provider(ABC):
    @abstractmethod
    def collect(self) -> list[Observation]: ...
