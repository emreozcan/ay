from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ay.values import LuaTable


class LibraryProvider(ABC):
    @abstractmethod
    def provide(self, table: LuaTable) -> None:
        pass
