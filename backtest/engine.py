"""Interface scaffold. No business implementation yet."""
class BacktestEngine:
    """Reserved extension interface."""

    def run(self, data, strategy, config):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
