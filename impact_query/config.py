import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class QuerySettings:
    default_vectorizer_path: str = "hashing_vectorizer.joblib"
    legacy_vectorizer_path: str = "tfidf_vectorizer.joblib"
    vectorizer_path: str = os.getenv("VECTORIZER_PATH", "hashing_vectorizer.joblib")
    db_conn: str = os.getenv(
        "DB_CONN",
        "dbname=knowledge_base user=admin password=password123 host=localhost",
    )
    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    openrouter_max_retries: int = int(os.getenv("OPENROUTER_MAX_RETRIES", "5"))
    openrouter_retry_delay: float = float(os.getenv("OPENROUTER_RETRY_DELAY", "5"))
    
    client_id: str = os.getenv("GENAI_CLIENT_ID", "")
    client_secret: str = os.getenv("GENAI_CLIENT_SECRET", "")

