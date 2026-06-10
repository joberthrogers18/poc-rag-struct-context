from pathlib import Path
from impact_indexing.config import IndexingSettings


def resolve_repo_and_team(base_dir: Path, file_path: Path) -> tuple[str, str]:
    """Extrai repo e time diretamente da convencao de pastas sample_projects/<repo>/<team>/..."""
    rel_path = file_path.relative_to(base_dir)
    parts = rel_path.parts
    if len(parts) < 2:
        raise ValueError(
            "Cada arquivo precisa estar em sample_projects/<repo>/<team>/..."
        )
    return parts[0], parts[1]


def resolve_relative_path(base_dir: Path, path_str: str) -> Path:
    """Normaliza caminhos recebidos por CLI para o mesmo formato usado pelo indexador."""
    path = Path(path_str)
    if path.is_absolute():
        return path
    return base_dir / path


def normalize_deleted_path(base_dir: Path, path_str: str) -> tuple[str, str, str]:
    """Converte o caminho de um arquivo deletado em chaves usadas pelo banco."""
    rel_path = Path(path_str)
    if rel_path.is_absolute():
        rel_path = rel_path.relative_to(base_dir)

    parts = rel_path.parts
    if len(parts) < 2:
        raise ValueError(
            "Cada arquivo deletado precisa estar em sample_projects/<repo>/<team>/..."
        )
    return parts[0], parts[1], str(rel_path)


def load_target_files(
    settings: IndexingSettings, cli_files: list[str] | None
) -> list[Path]:
    """Decide se a rodada vai processar um conjunto explicito de arquivos ou o dataset inteiro."""

    if cli_files:
        return [
            resolve_relative_path(settings.base_dir, path_str) for path_str in cli_files
        ]

    files = []
    ignored_terms_files = {"_test.js", "_spec.js", "test_", "spec_"}
    ignored_terms_dirs = {"__tests__", "tests", "test", "node_modules", "vendor"}

    for file_path in settings.base_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix in settings.supported_suffixes:
            if any(term in file_path.name for term in ignored_terms_files) or any(
                term in file_path.parts for term in ignored_terms_dirs
            ):
                continue

            files.append(file_path)

    return files
