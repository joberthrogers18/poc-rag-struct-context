import logging
from psycopg2.extras import RealDictCursor
from impact_query.search import dedupe_artifacts

logger = logging.getLogger(__name__)


def expand_related_artifacts(conn, artifacts: list[dict]) -> list[dict]:
    """Busca recursivamente todos os artefatos dependentes (impacto para baixo).

    Caminha pelo grafo de 'artifact_id' para 'related_id' de forma recursiva,
    garantindo que se A impacta B e B impacta C, ambos sejam retornados.
    Includes proteção nativa contra dependências circulares (loops).
    """
    initial_ids = [art.get("id") for art in artifacts if art.get("id")]
    if not initial_ids:
        return artifacts

    expanded = list(artifacts)

    # Query recursiva calibrada para o seu DDL (rastreando dependentes)
    recursive_query = """
        WITH RECURSIVE downstream_impact AS (
            -- Âncora: Encontra os primeiros dependentes diretos
            SELECT 
                related_id,
                ARRAY[artifact_id, related_id] AS visited_path,
                1 AS depth
            FROM artifact_relations 
            WHERE artifact_id = ANY(%s)
            
            UNION ALL
            
            -- Membro Recursivo: Encontra dependentes em cascata
            SELECT 
                r.related_id,
                di.visited_path || r.related_id AS visited_path,
                di.depth + 1 AS depth
            FROM artifact_relations r
            INNER JOIN downstream_impact di ON r.artifact_id = di.related_id
            -- Trava 1: Impede ciclo (não visita o que já está no caminho)
            WHERE NOT (r.related_id = ANY(di.visited_path))
            -- Trava 2: Profundidade máxima (evita explosão de memória e gasto de tokens do LLM)
              AND di.depth < 3
        )
        -- Seleciona os dados completos apenas com IDs únicos (deduplicação feita no final)
        SELECT id, repo, team, path, block_name, block_type,
              block_start_line, block_end_line, summary,
              tables_ref, columns_ref, content
        FROM artifact_chunks
        WHERE id IN (SELECT DISTINCT related_id FROM downstream_impact);
    """

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(recursive_query, (initial_ids,))
            rows = cur.fetchall()

            # Adiciona os novos artefatos dependentes encontrados na lista original
            expanded.extend(dict(row) for row in rows)

    except Exception as exc:
        logger.error("Erro ao expandir dependentes no banco de dados: %s", exc)

    # Remove possíveis duplicatas caso um artefato tenha sido descoberto por mais de um caminho
    return dedupe_artifacts(expanded)
