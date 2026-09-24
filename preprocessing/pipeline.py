"""Interface scaffold. No business implementation yet."""
class PreprocessingPipeline:
    """Reserved extension interface."""

    def run(self, data):
        """Implement after input/output contracts are confirmed."""
        raise NotImplementedError("This interface is not implemented.")
