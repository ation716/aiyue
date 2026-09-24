"""Interface scaffold. No business implementation yet."""
class DataAccessObject:
    """Reserved extension interface."""

    def upsert(self, records):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
