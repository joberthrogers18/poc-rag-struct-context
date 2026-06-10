import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Carrega variáveis de ambiente
load_dotenv()


@dataclass(frozen=True)
class IndexingSettings:
    """
    Configurações para o processo de indexação, carregadas de variáveis de ambiente.
    """

    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    db_conn: str = os.getenv(
        "DB_CONN",
        "dbname=knowledge_base user=admin password=password123 host=localhost",
    )
    base_dir: Path = Path("sample_projects")
    hash_dim: int = 384
    openrouter_max_retries: int = int(os.getenv("OPENROUTER_MAX_RETRIES", "5"))
    openrouter_retry_delay: float = float(os.getenv("OPENROUTER_RETRY_DELAY", "5.0"))
    source_type: str = "code"

    supported_suffixes: tuple[str, ...] = (".js", ".ts", ".prisma", ".py")
    client_id: str = os.getenv("GENAI_CLIENT_ID", "")
    client_secret: str = os.getenv("GENAI_CLIENT_SECRET", "")
