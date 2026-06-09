import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class IndexingSettings:
    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    db_conn: str = os.getenv(
        "DB_CONN",
        "dbname=knowledge_base user=admin password=password123 host=localhost",
    )
    base_dir: Path = Path("sample_projects")
    hash_dim: int = 384
    openrouter_max_retries: int = int(os.getenv("OPENROUTER_MAX_RETRIES", "5"))
    openrouter_retry_delay: float = float(os.getenv("OPENROUTER_RETRY_DELAY", "5"))
    source_type: str = "code"
    supported_suffixes: tuple[str, ...] = field(
        default_factory=lambda: (".js", ".ts", ".prisma")
    )

