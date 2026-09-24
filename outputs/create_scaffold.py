"""Create missing scaffold files only; never overwrite existing files."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
MODULES = {
    "data/connectors/base_connector.py": ("BaseConnector", "fetch", "self, **kwargs"),
    "data/connectors/data_connector.py": ("DataConnector", "fetch", "self, **kwargs"),
    "data/connectors/db_connector.py": ("DBConnector", "connect", "self"),
    "data/storage/models.py": ("ModelRegistry", "register", "self, model"),
    "data/storage/dao.py": ("DataAccessObject", "upsert", "self, records"),
    "preprocessing/cleaner.py": ("DataCleaner", "transform", "self, data"),
    "preprocessing/indicators.py": ("IndicatorCalculator", "transform", "self, data"),
    "preprocessing/factors.py": ("FactorCalculator", "transform", "self, data"),
    "preprocessing/pipeline.py": ("PreprocessingPipeline", "run", "self, data"),
    "scoring/base_scorer.py": ("BaseScorer", "score", "self, data"),
    "scoring/technical_scorer.py": ("TechnicalScorer", "score", "self, data"),
    "scoring/fundamental_scorer.py": ("FundamentalScorer", "score", "self, data"),
    "scoring/sentiment_scorer.py": ("SentimentScorer", "score", "self, data"),
    "scoring/momentum_scorer.py": ("MomentumScorer", "score", "self, data"),
    "scoring/composite_scorer.py": ("CompositeScorer", "score", "self, data"),
    "scoring/filters.py": ("BaseFilter", "apply", "self, data"),
    "scoring/ranker.py": ("Ranker", "rank", "self, scores"),
    "scoring/selector.py": ("Selector", "select", "self, scores"),
    "scoring/universe.py": ("Universe", "get_symbols", "self, as_of"),
    "portfolio/position_sizer.py": ("PositionSizer", "calculate", "self, selected, context"),
    "portfolio/allocator.py": ("Allocator", "allocate", "self, weights, context"),
    "portfolio/rebalancer.py": ("Rebalancer", "rebalance", "self, current, target"),
    "portfolio/risk_control.py": ("RiskControl", "check", "self, target, context"),
    "backtest/engine.py": ("BacktestEngine", "run", "self, data, strategy, config"),
    "backtest/broker.py": ("Broker", "execute", "self, orders, context"),
    "backtest/performance.py": ("PerformanceCalculator", "calculate", "self, history"),
    "backtest/report.py": ("ReportGenerator", "generate", "self, result, destination"),
    "backtest/visualizer.py": ("Visualizer", "render", "self, result, destination"),
    "strategies/base_strategy.py": ("BaseStrategy", "generate", "self, data, context"),
    "strategies/multi_factor_strategy.py": ("MultiFactorStrategy", "generate", "self, data, context"),
}

created = []
def add(relative, content):
    path = ROOT / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        created.append(relative)

for package in ["config", "data", "data/connectors", "data/storage", "preprocessing", "scoring", "selection", "portfolio", "backtest", "strategies", "utils", "scripts", "tests"]:
    add(f"{package}/__init__.py", '"""Package scaffold; business implementation is pending."""\n')
for relative, (name, method, args) in MODULES.items():
    abstract = name in {"BaseConnector", "BaseScorer", "BaseStrategy"}
    imports = "from abc import ABC, abstractmethod\n\n\n" if abstract else ""
    parent = "(ABC)" if abstract else ""
    decorator = "    @abstractmethod\n" if abstract else ""
    add(relative, f'"""Interface scaffold. No business implementation yet."""\n{imports}class {name}{parent}:\n    """Reserved extension interface."""\n\n{decorator}    def {method}({args}):\n        """Implement after input/output contracts are confirmed."""\n        raise NotImplementedError("This interface is not implemented.")\n')
for directory in ["data/raw/daily", "data/raw/financial", "data/raw/minute", "data/processed/factors", "data/processed/indicators", "logs", "output/reports", "output/figures"]:
    add(f"{directory}/.gitkeep", "")
add("data/storage/schema.sql", "-- Schema scaffold only. No DDL is executed.\n-- Confirm DB dialect, keys, types and migration policy before implementation.\n")
for relative, function, args in [
    ("utils/date_utils.py", "get_calendar", "start, end"),
    ("utils/decorators.py", "retry", "*args, **kwargs"),
    ("utils/helpers.py", "validate_input", "data"),
]:
    add(relative, f'"""Utility interface scaffold."""\n\ndef {function}({args}):\n    raise NotImplementedError("This utility is not implemented.")\n')
for name in ["init_db", "update_data", "run_backtest", "run_daily"]:
    add(f"scripts/{name}.py", '"""Inactive entry scaffold; no external side effects."""\n\ndef main():\n    raise SystemExit("Not implemented. No operation was performed.")\n\n\nif __name__ == "__main__":\n    main()\n')
for name in ["connectors", "indicators", "scoring", "backtest"]:
    add(f"tests/test_{name}.py", f'"""Pending contract tests; intentionally not reported as passed."""\nimport unittest\n\n\n@unittest.skip("Business implementation and contracts are pending")\nclass Test{name.title()}(unittest.TestCase):\n    def test_contract_pending(self):\n        self.fail("Replace with contract assertions before enabling this test.")\n')
add("notebooks/research.ipynb", json.dumps({"cells": [{"cell_type": "markdown", "metadata": {}, "source": ["# Research scaffold\n", "No data loaded and no computation executed.\n", "Record configuration before each experiment."]}], "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}, indent=2) + "\n")
print(json.dumps({"created_count": len(created), "status": "scaffold_only"}))
