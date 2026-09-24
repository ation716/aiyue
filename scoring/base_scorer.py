"""Interface scaffold. No business implementation yet."""
from abc import ABC, abstractmethod


class BaseScorer(ABC):
    """Reserved extension interface."""

    @abstractmethod
    def score(self, data):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
