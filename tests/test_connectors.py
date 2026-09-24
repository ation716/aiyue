"""Pending contract tests; intentionally not reported as passed."""
import unittest


@unittest.skip("Business implementation and contracts are pending")
class TestConnectors(unittest.TestCase):
    def test_contract_pending(self):
        self.fail("Replace with contract assertions before enabling this test.")
