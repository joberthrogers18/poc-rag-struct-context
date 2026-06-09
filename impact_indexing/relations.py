import re
from pathlib import Path

from impact_indexing.storage import fetch_all_artifacts, fetch_file_artifacts


IMPORT_RE = re.compile(r'import\s+.*?\s+from\s+[\'"](.+?)[\'"]')
DERIVED_FIELD_PAIRS = [
    ("createdat", "signupdate"),
    ("created_at", "signup_date"),
]


def normalize_token(value: str) -> str:
    # Normaliza texto para comparacoes simples entre naming conventions diferentes.
    return re.sub(r"[^a-z0-9]", "", value.lower())


def build_import_targets(base_dir: Path, source_file: Path) -> set[str]:
    # Resolve imports relativos para paths canonicos dentro de sample_projects.
    if not source_file.exists():
        return set()
    content = source_file.read_text(encoding="utf-8")
    targets = set()
    for match in IMPORT_RE.findall(content):
        if not match.startswith("."):
            continue
        candidate = (source_file.parent / match).resolve()
        possible_files = [
            candidate,
            candidate.with_suffix(".js"),
            candidate.with_suffix(".ts"),
        ]
        for possible in possible_files:
            try:
                rel = possible.relative_to(base_dir.resolve())
                targets.add(str(rel))
                break
            except ValueError:
                continue
    return targets


def create_relation(cur, artifact_id: int, related_id: int, relation_type: str, confidence: str, reason: str):
    # Faz upsert da relacao para manter o grafo recalculavel sem duplicatas.
    if artifact_id == related_id:
        return
    cur.execute(
        """
        INSERT INTO artifact_relations (artifact_id, related_id, relation_type, confidence, reason, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (artifact_id, related_id, relation_type)
        DO UPDATE SET
            confidence = EXCLUDED.confidence,
            reason = EXCLUDED.reason,
            updated_at = NOW()
        """,
        (artifact_id, related_id, relation_type, confidence, reason),
    )


def rebuild_relations_for_files(conn, base_dir: Path, file_keys: list[tuple[str, str, str]]):
    # Reconstroi apenas as relacoes tocadas pelos arquivos alterados para manter o processo incremental.
    impacted_artifacts = fetch_file_artifacts(conn, file_keys)
    if not impacted_artifacts:
        return

    impacted_ids = [artifact["id"] for artifact in impacted_artifacts]
    with conn.cursor() as cur:
        # Primeiro invalida as relacoes antigas dos artefatos impactados.
        cur.execute(
            """
            DELETE FROM artifact_relations
            WHERE artifact_id = ANY(%s) OR related_id = ANY(%s)
            """,
            (impacted_ids, impacted_ids),
        )
    conn.commit()

    all_artifacts = fetch_all_artifacts(conn)
    artifacts_by_path = {}
    for artifact in all_artifacts:
        artifacts_by_path.setdefault(artifact["path"], []).append(artifact)

    import_targets_by_path = {}
    for repo_name, team_name, rel_path in file_keys:
        source_file = base_dir / rel_path
        import_targets_by_path[rel_path] = build_import_targets(base_dir, source_file)

    with conn.cursor() as cur:
        for artifact in impacted_artifacts:
            artifact_tables = set(artifact.get("tables_ref") or [])
            artifact_columns = set(artifact.get("columns_ref") or [])
            artifact_content_normalized = normalize_token(artifact.get("content") or "")

            for other in all_artifacts:
                if artifact["id"] == other["id"]:
                    continue

                other_tables = set(other.get("tables_ref") or [])
                other_columns = set(other.get("columns_ref") or [])
                other_content_normalized = normalize_token(other.get("content") or "")

                shared_tables = sorted(artifact_tables & other_tables)
                if shared_tables:
                    # Shared table costuma ser um bom sinal de dependencia direta de dados.
                    create_relation(
                        cur,
                        artifact["id"],
                        other["id"],
                        "shared_table",
                        "high",
                        f"Tabelas compartilhadas: {', '.join(shared_tables)}",
                    )

                shared_columns = sorted(artifact_columns & other_columns)
                if shared_columns:
                    # Shared column aumenta recall de impacto mesmo quando a tabela nao foi bem inferida.
                    create_relation(
                        cur,
                        artifact["id"],
                        other["id"],
                        "shared_column",
                        "medium",
                        f"Colunas compartilhadas: {', '.join(shared_columns)}",
                    )

                for left, right in DERIVED_FIELD_PAIRS:
                    if left in artifact_content_normalized and right in other_content_normalized:
                        # Captura transformacoes comuns como createdAt -> signupDate.
                        create_relation(
                            cur,
                            artifact["id"],
                            other["id"],
                            "derived_field",
                            "medium",
                            f"Campo derivado detectado: {left} -> {right}",
                        )

            import_targets = import_targets_by_path.get(artifact["path"], set())
            for import_target in import_targets:
                for related_artifact in artifacts_by_path.get(import_target, []):
                    # Import explicito e o sinal mais confiavel de dependencia entre arquivos.
                    create_relation(
                        cur,
                        artifact["id"],
                        related_artifact["id"],
                        "imports",
                        "high",
                        f"Import explicito do arquivo {artifact['path']} para {import_target}",
                    )
    conn.commit()
