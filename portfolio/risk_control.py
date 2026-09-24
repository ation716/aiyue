"""Interface scaffold. No business implementation yet."""
class RiskControl:
    """Reserved extension interface."""

    def check(self, target, context):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
