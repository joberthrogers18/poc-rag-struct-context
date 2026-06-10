import hashlib
import psycopg2


def ensure_tables(conn, source_type: str):
    # Garante que o banco tenha todas as tabelas e colunas esperadas pelo pipeline atual.
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS artifact_files (
                id SERIAL PRIMARY KEY,
                repo TEXT NOT NULL,
                team TEXT NOT NULL,
                path TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT '{source_type}',
                status TEXT NOT NULL DEFAULT 'active',
                last_indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (repo, team, path)
            );
            """)
        cur.execute("""
            ALTER TABLE artifact_chunks
            ADD COLUMN IF NOT EXISTS content_hash TEXT;
            """)
        cur.execute("""
            ALTER TABLE artifact_chunks
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS artifact_chunks_lookup_idx
            ON artifact_chunks (repo, team, path);
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS artifact_relations (
                id SERIAL PRIMARY KEY,
                artifact_id INTEGER NOT NULL REFERENCES artifact_chunks(id) ON DELETE CASCADE,
                related_id INTEGER NOT NULL REFERENCES artifact_chunks(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL,
                confidence TEXT NOT NULL DEFAULT 'medium',
                reason TEXT,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (artifact_id, related_id, relation_type)
            );
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS artifact_relations_artifact_idx
            ON artifact_relations (artifact_id);
            """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS artifact_relations_related_idx
            ON artifact_relations (related_id);
            """)
    conn.commit()


def compute_content_hash(content: str) -> str:
    # O hash e a base da indexacao incremental por arquivo.
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def check_hash_exists(conn, content_hash: str) -> bool:
    """
    Verifica se o hash do arquivo já foi processado e existe no banco de dados.
    """
    # Se por algum motivo o hash vier vazio, força o processamento
    if not content_hash:
        return False

    query = """
        SELECT EXISTS(
            SELECT 1 FROM artifact_chunks WHERE content_hash = %s
        );
    """

    try:
        with conn.cursor() as cur:
            cur.execute(query, (content_hash,))
            # fetchone()[0] vai retornar True se encontrar ou False se não encontrar
            exists = cur.fetchone()[0]
            return exists
    except Exception as e:
        print(f"[ERRO BANDO] Falha ao verificar hash no banco: {e}")
        # Por segurança, se der erro no banco, retornamos False para processar o arquivo
        return False


def get_indexed_file_hash(
    conn, repo_name: str, team_name: str, rel_path: str
) -> str | None:
    # Consulta o ultimo hash conhecido para decidir se vale reprocessar o arquivo.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT content_hash
            FROM artifact_files
            WHERE repo = %s AND team = %s AND path = %s AND status = 'active'
            """,
            (repo_name, team_name, rel_path),
        )
        row = cur.fetchone()
    return row[0] if row else None


def mark_file_deleted(
    conn, repo_name: str, team_name: str, rel_path: str, source_type: str
):
    """Remove chunks do arquivo e marca o path como deletado no catalogo de arquivos."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM artifact_chunks
            WHERE repo = %s AND team = %s AND path = %s
            """,
            (repo_name, team_name, rel_path),
        )
        cur.execute(
            """
            INSERT INTO artifact_files (repo, team, path, content_hash, source_type, status, last_indexed_at)
            VALUES (%s, %s, %s, %s, %s, 'deleted', NOW())
            ON CONFLICT (repo, team, path)
            DO UPDATE SET
                content_hash = EXCLUDED.content_hash,
                source_type = EXCLUDED.source_type,
                status = 'deleted',
                last_indexed_at = NOW()
            """,
            (repo_name, team_name, rel_path, "deleted", source_type),
        )
    conn.commit()


def replace_file_artifacts(
    conn,
    repo_name: str,
    team_name: str,
    rel_path: str,
    content_hash: str,
    artefatos: list[dict],
    source_type: str,
):
    """Substitui todos os chunks de um arquivo pela versao mais recente reconstruida."""
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM artifact_chunks
            WHERE repo = %s AND team = %s AND path = %s
            """,
            (repo_name, team_name, rel_path),
        )

        for artefato in artefatos:
            cur.execute(
                """
                INSERT INTO artifact_chunks
                (repo, team, path, block_name, block_type, block_start_line, block_end_line, content, tables_ref, columns_ref, summary, embedding, content_hash, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    artefato["repo"],
                    artefato["team"],
                    artefato["path"],
                    artefato["block_name"],
                    artefato["block_type"],
                    artefato["linha_inicio"],
                    artefato["linha_fim"],
                    artefato["codigo"],
                    artefato["tabelas"],
                    artefato["colunas"],
                    artefato["resumo"],
                    artefato["embedding"],
                    content_hash,
                ),
            )

        cur.execute(
            """
            INSERT INTO artifact_files (repo, team, path, content_hash, source_type, status, last_indexed_at)
            VALUES (%s, %s, %s, %s, %s, 'active', NOW())
            ON CONFLICT (repo, team, path)
            DO UPDATE SET
                content_hash = EXCLUDED.content_hash,
                source_type = EXCLUDED.source_type,
                status = 'active',
                last_indexed_at = NOW()
            """,
            (repo_name, team_name, rel_path, content_hash, source_type),
        )
    conn.commit()


def fetch_file_artifacts(conn, file_keys: list[tuple[str, str, str]]) -> list[dict]:
    """Carrega apenas os artefatos dos arquivos impactados nesta rodada."""
    artifacts = []
    with conn.cursor() as cur:
        for repo_name, team_name, rel_path in file_keys:
            cur.execute(
                """
                SELECT id, repo, team, path, block_name, block_type, content, tables_ref, columns_ref, summary
                FROM artifact_chunks
                WHERE repo = %s AND team = %s AND path = %s
                """,
                (repo_name, team_name, rel_path),
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            artifacts.extend(dict(zip(cols, row)) for row in rows)
    return artifacts


def fetch_all_artifacts(conn) -> list[dict]:
    """Relacoes heuristicas precisam enxergar o conjunto completo ja indexado."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, repo, team, path, block_name, block_type, content, tables_ref, columns_ref, summary
            FROM artifact_chunks
            """)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in rows]
