"""Interface scaffold. No business implementation yet."""
class Rebalancer:
    """Reserved extension interface."""

    def rebalance(self, current, target):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
