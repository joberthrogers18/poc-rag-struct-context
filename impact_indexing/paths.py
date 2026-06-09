from pathlib import Path

from impact_indexing.config import IndexingSettings


def resolve_repo_and_team(base_dir: Path, file_path: Path) -> tuple[str, str]:
    rel_path = file_path.relative_to(base_dir)
    parts = rel_path.parts
    if len(parts) < 2:
        raise ValueError(
            "Cada arquivo precisa estar em sample_projects/<repo>/<team>/..."
        )
    return parts[0], parts[1]


def resolve_relative_path(base_dir: Path, path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return base_dir / path


def normalize_deleted_path(base_dir: Path, path_str: str) -> tuple[str, str, str]:
    rel_path = Path(path_str)
    if rel_path.is_absolute():
        rel_path = rel_path.relative_to(base_dir)

    parts = rel_path.parts
    if len(parts) < 2:
        raise ValueError(
            "Cada arquivo deletado precisa estar em sample_projects/<repo>/<team>/..."
        )
    return parts[0], parts[1], str(rel_path)


def load_target_files(settings: IndexingSettings, cli_files: list[str] | None) -> list[Path]:
    if cli_files:
        return [resolve_relative_path(settings.base_dir, path_str) for path_str in cli_files]

    files = []
    for file_path in settings.base_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix in settings.supported_suffixes:
            files.append(file_path)
    return files

