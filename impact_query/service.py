import json
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector

from impact_query.config import QuerySettings
from impact_query.context_builder import build_llm_context, build_report
from impact_query.llm_client import call_openrouter_for_report
from impact_query.relations import expand_related_artifacts
from impact_query.search import dedupe_artifacts, search_artifacts
from impact_query.vectorizer import load_vectorizer


@contextmanager
def _get_db_connection(db_conn_str: str):
    """Gerenciador de contexto que garante a abertura, registro do pgvector e fechamento seguro da conexão."""
    conn = psycopg2.connect(db_conn_str)
    try:
        register_vector(conn)
    except Exception:
        # Silencia falhas caso o tipo vector já esteja registrado na sessão/banco
        pass
    try:
        yield conn
    finally:
        conn.close()


def search_impact_code(pergunta: str, settings: QuerySettings | None = None) -> list[dict]:
    """Retorna somente os artefatos candidatos para debug ou exploracao manual."""
    settings = settings or QuerySettings()
    vectorizer = load_vectorizer(settings)
    
    with _get_db_connection(settings.db_conn) as conn:
        return search_artifacts(conn, vectorizer, pergunta)


def generate_impact_report(
    pergunta: str | None = None,
    ids: list[int] | None = None,
    settings: QuerySettings | None = None,
) -> dict:
    """Orquestra a consulta inteira: busca, expansao por relacoes, contexto e resposta final."""
    if ids is None and pergunta is None:
        return {"error": "Informe 'ids' ou 'pergunta'"}

    settings = settings or QuerySettings()
    artifacts = []

    with _get_db_connection(settings.db_conn) as conn:
        if ids:
            # RealDictCursor faz o mapeamento coluna -> valor automaticamente em formato de dict
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT id, repo, team, path, block_name, block_type,
                           block_start_line, block_end_line, summary,
                           tables_ref, columns_ref, content
                    FROM artifact_chunks
                    WHERE id = ANY(%s)
                    """,
                    (ids,),
                )
                # Como RealDictCursor retorna instâncias de RealDict, convertemos para dict puro se necessário
                artifacts.extend(dict(row) for row in cur.fetchall())
        else:
            vectorizer = load_vectorizer(settings)
            artifacts.extend(search_artifacts(conn, vectorizer, pergunta))

        artifacts = dedupe_artifacts(artifacts)
        # Expande a busca com relacoes persistidas para capturar consumidores indiretos
        artifacts = expand_related_artifacts(conn, artifacts)

    # O banco já fechou com segurança aqui. Agora processamos a inteligência/LLM.
    report = build_report(artifacts)
    llm_context = build_llm_context(report, pergunta, artifacts)
    answer = call_openrouter_for_report(settings, pergunta, llm_context, report)

    return {
        "answer": answer,
        "artifacts": artifacts,
        "report": report,
        "context": llm_context,
    }


def search_impact_code_json(pergunta: str, settings: QuerySettings | None = None) -> str:
    """Mantem compatibilidade com a camada CLI que espera uma string JSON."""
    return json.dumps(search_impact_code(pergunta, settings), ensure_ascii=False)


def generate_impact_report_text(
    pergunta: str | None = None,
    ids: list[int] | None = None,
    settings: QuerySettings | None = None,
) -> str:
    """Devolve apenas o texto final para clients simples como CLI ou bot."""
    result = generate_impact_report(pergunta=pergunta, ids=ids, settings=settings)
    return json.dumps(result, ensure_ascii=False) if "error" in result else result["answer"]