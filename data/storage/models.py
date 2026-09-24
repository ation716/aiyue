"""Interface scaffold. No business implementation yet."""
class ModelRegistry:
    """Reserved extension interface."""

    def register(self, model):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
