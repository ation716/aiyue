"""Interface scaffold. No business implementation yet."""
class Broker:
    """Reserved extension interface."""

    def execute(self, orders, context):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
