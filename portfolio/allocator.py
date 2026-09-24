"""Interface scaffold. No business implementation yet."""
class Allocator:
    """Reserved extension interface."""

    def allocate(self, weights, context):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
