from pathlib import Path
import joblib

from impact_query.config import QuerySettings


def load_vectorizer(settings: QuerySettings):
    """Carrega o vetorizador atual ou o legado para compatibilidade.
    
    Lança FileNotFoundError se nenhum arquivo válido for encontrado.
    """
    primary_path = Path(settings.vectorizer_path)
    legacy_path = Path(settings.legacy_vectorizer_path)

    # 1. Se o caminho principal existir, usa ele direto
    if primary_path.exists():
        return joblib.load(primary_path)

    # 2. Se não existir, avalia a regra de negócio para o fallback legado
    is_using_default = settings.vectorizer_path == settings.default_vectorizer_path
    if is_using_default and legacy_path.exists():
        return joblib.load(legacy_path)

    # 3. Se nenhum dos dois existir, lança a exceção explicativa
    raise FileNotFoundError(
        f"Vetorizador não encontrado em '{primary_path}'.\n"
        f"Rode o 'ingest.py' para gerar '{settings.default_vectorizer_path}' "
        f"ou defina a variável de ambiente 'VECTORIZER_PATH' explicitamente."
    )