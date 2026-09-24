"""Interface scaffold. No business implementation yet."""
class DataCleaner:
    """Reserved extension interface."""

    def transform(self, data):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
