"""Interface scaffold. No business implementation yet."""
class CompositeScorer:
    """Reserved extension interface."""

    def score(self, data):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
