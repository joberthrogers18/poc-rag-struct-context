import argparse
import sys
import genai_sdk

import psycopg2
from pgvector.psycopg2 import register_vector

from impact_indexing.config import IndexingSettings
from impact_indexing.indexer import build_embeddings, process_file
from impact_indexing.paths import (
    load_target_files,
    normalize_deleted_path,
    resolve_repo_and_team,
)
from impact_indexing.relations import rebuild_relations_for_files
from impact_indexing.storage import (
    compute_content_hash,
    ensure_tables,
    get_indexed_file_hash,
    mark_file_deleted,
    replace_file_artifacts,
)


def parse_args():
    """Responsável por parsear os argumentos de linha de comando para a ingestão."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--files",
        nargs="*",
        help="Arquivos alterados para reindexar. Caminhos relativos a sample_projects/ ou absolutos.",
    )
    parser.add_argument(
        "--deleted-files",
        nargs="*",
        default=[],
        help="Arquivos removidos do repo para limpar no índice.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocessa mesmo quando o content_hash nao mudou.",
    )
    return parser.parse_args()


def sync_deleted_files(conn, settings: IndexingSettings, deleted_files: list[str]):
    """Sincroniza arquivos deletados, removendo-os do índice."""
    for deleted_path in deleted_files:
        repo_name, team_name, rel_path = normalize_deleted_path(
            settings.base_dir, deleted_path
        )
        mark_file_deleted(conn, repo_name, team_name, rel_path, settings.source_type)
        print(f"[INDEX] Removido do índice: {rel_path}")


def collect_changed_files(
    conn, settings: IndexingSettings, cli_files: list[str] | None, force: bool
):
    """Coleta arquivos que precisam ser processados, comparando hashes e respeitando a flag de força."""
    processed_files = []
    target_files = load_target_files(settings, cli_files)

    for file_path in target_files:
        if not file_path.exists():
            print(f"[INDEX] Arquivo ignorado porque nao existe: {file_path}")
            continue
        if (
            not file_path.is_file()
            or file_path.suffix not in settings.supported_suffixes
        ):
            continue

        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        repo_name, team_name = resolve_repo_and_team(settings.base_dir, file_path)
        rel_path = str(file_path.relative_to(settings.base_dir))
        content_hash = compute_content_hash(raw_content)
        indexed_hash = get_indexed_file_hash(conn, repo_name, team_name, rel_path)
        if indexed_hash == content_hash and not force:
            print(f"[INDEX] Sem mudanças, pulando: {rel_path}")
            continue

        artefatos, repo_name, team_name, rel_path, content_hash = process_file(
            conn, settings, file_path
        )
        processed_files.append(
            {
                "repo": repo_name,
                "team": team_name,
                "path": rel_path,
                "content_hash": content_hash,
                "artefatos": artefatos,
            }
        )

    return processed_files


def persist_processed_files(
    conn, settings: IndexingSettings, processed_files: list[dict]
):
    """Persist processed files to the database and rebuild relations."""
    all_artifacts = build_embeddings(processed_files)
    rebuilt_file_keys = []

    for entry in processed_files:
        replace_file_artifacts(
            conn,
            entry["repo"],
            entry["team"],
            entry["path"],
            entry["content_hash"],
            entry["artefatos"],
            settings.source_type,
        )
        rebuilt_file_keys.append((entry["repo"], entry["team"], entry["path"]))

    if rebuilt_file_keys:
        rebuild_relations_for_files(conn, settings.base_dir, rebuilt_file_keys)

    return all_artifacts


def main():
    """Main entry point for the indexing ingestion process."""
    INICIATIVE_DATA = "inic786"
    args = parse_args()
    settings = IndexingSettings()

    if not settings.client_id or not settings.client_secret:
        raise RuntimeError(
            "Defina GENAI_CLIENT_ID e GENAI_CLIENT_SECRET no ambiente antes de rodar a ingestão."
        )

    genai_sdk.init(
        env="exploration",  # ambiente de exploração (ligue VPN)
        identificadores=INICIATIVE_DATA,  # iniciativa promotool
        project_id="gen-ai-tools-developer",
        client_id=settings.client_id,
        client_secret=settings.client_secret,
    )

    conn = psycopg2.connect(settings.db_conn)
    ensure_tables(conn, settings.source_type)
    register_vector(conn)

    sync_deleted_files(conn, settings, args.deleted_files)
    processed_files = collect_changed_files(conn, settings, args.files, args.force)

    if not processed_files:
        conn.close()
        print("[INDEX] Nenhum arquivo novo ou alterado para indexar. Encerrando.")
        sys.exit(0)

    all_artefatos = persist_processed_files(conn, settings, processed_files)
    conn.close()

    print(
        f"[INDEX] Ingestão concluída. {len(all_artefatos)} blocos sincronizados em {len(processed_files)} arquivo(s)."
    )


if __name__ == "__main__":
    main()
