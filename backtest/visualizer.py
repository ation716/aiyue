"""Interface scaffold. No business implementation yet."""
class Visualizer:
    """Reserved extension interface."""

    def render(self, result, destination):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
