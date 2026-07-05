from abc import ABC, abstractmethod
from typing import List

from scout.models import Business


class BusinessSource(ABC):
    @abstractmethod
    def get_businesses(self, query: str, location: str, radius: int) -> List[Business]:
        ...
