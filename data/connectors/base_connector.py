"""Interface scaffold. No business implementation yet."""
from abc import ABC, abstractmethod


class BaseConnector(ABC):
    """Reserved extension interface."""

    @abstractmethod
    def fetch(self, **kwargs):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
