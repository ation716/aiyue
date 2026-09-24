"""Read-only structural validation; does not import or execute project modules."""
import ast
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
packages = {
    "config": "__init__ settings logging_config",
    "data": "__init__",
    "data/connectors": "__init__ base_connector data_connector db_connector",
    "data/storage": "__init__ models dao",
    "preprocessing": "__init__ cleaner indicators factors pipeline",
    "scoring": "__init__ base_scorer technical_scorer fundamental_scorer sentiment_scorer momentum_scorer composite_scorer",
    "selection": "__init__ filters ranker selector universe",
    "portfolio": "__init__ position_sizer allocator rebalancer risk_control",
    "backtest": "__init__ engine broker performance report visualizer",
    "strategies": "__init__ base_strategy multi_factor_strategy",
    "utils": "__init__ logger date_utils decorators helpers",
    "scripts": "init_db update_data run_backtest run_daily",
    "tests": "test_connectors test_indicators test_scoring test_backtest",
}
expected = [f"{directory}/{name}.py" for directory, names in packages.items() for name in names.split()]
expected += ["main.py", "README.md", "requirements.txt", ".gitignore", "data/storage/schema.sql", "notebooks/research.ipynb"]
missing = [p for p in expected if not (root / p).is_file()]
directories = ["data/raw/daily", "data/raw/financial", "data/raw/minute", "data/processed/factors", "data/processed/indicators", "logs", "output/reports", "output/figures"]
assert not missing, missing
assert all((root / p).is_dir() for p in directories)
files = [p for p in root.rglob("*.py") if ".workbuddy" not in p.parts]
for path in files:
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
book = json.loads((root / "notebooks/research.ipynb").read_text(encoding="utf-8"))
assert book["nbformat"] == 4
assert not any(c["cell_type"] == "code" for c in book["cells"])
terms = (root / "ai_rules/answer_terms.txt").read_text(encoding="utf-8").split()
text = (root / "README.md").read_text(encoding="utf-8")
assert not any(word in text for word in terms), "Text validation failed"
print(json.dumps({"required_files": len(expected), "missing": len(missing), "python_ast_pass": len(files), "required_directories": len(directories), "notebook_json": "pass", "text_check": "pass", "business_execution": False}))
