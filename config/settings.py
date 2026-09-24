"""Environment-based configuration; importing this module has no side effects."""
from dataclasses import dataclass, field
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT
    database_url: str = field(default="", repr=False)
    tushare_token: str = field(default="", repr=False)
    data_provider: str = ""
    log_level: str = "INFO"
    exp_id: str = ""

    @property
    def results_dir(self) -> Path:
        return self.project_root / "results"

    @property
    def logs_dir(self) -> Path:
        return self.project_root / "logs"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            tushare_token=os.getenv("TUSHARE_TOKEN", ""),
            data_provider=os.getenv("DATA_PROVIDER", ""),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            exp_id=os.getenv("EXP_ID", ""),
        )
