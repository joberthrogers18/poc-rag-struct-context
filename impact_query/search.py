import json
import re

from genai_sdk.model_enums import EmbeddingModels, EmbeddingTask, Models
from genai_sdk.frameworks.langchain.boti_embeddings_langchain import (
    BotiEmbeddingsLangChain,
)

def vector_to_pg(value: list[float]) -> str:
    # Converte a lista Python para o formato textual aceito pelo operador vector do Postgres.
    return "[" + ",".join(str(float(v)) for v in value) + "]"


def extract_query_terms(pergunta: str) -> list[str]:
    # Expande a pergunta com termos proximos do dominio para melhorar a busca lexical.
    base_terms = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", (pergunta or "").lower()))

    expanded_terms = set(base_terms)
    if {"usuario", "usuários", "usuarios", "user"} & base_terms:
        expanded_terms.update({"user", "users", "customer-api"})
    if {"criados", "criacao", "criação", "recentemente", "recentes", "recent"} & base_terms:
        expanded_terms.update(
            {
                "createdat",
                "created_at",
                "createdafter",
                "createdAfter",
                "signupdate",
                "snapshot",
                "recent",
                "recentes",
            }
        )
    if {"consome", "consumem", "consumo", "usa", "usam"} & base_terms:
        expanded_terms.update(
            {
                "pipeline",
                "job",
                "export",
                "snapshot",
                "sourceReference",
                "send",
            }
        )
    if {"etl", "dados", "data", "analytics"} & base_terms:
        expanded_terms.update({"etl", "pipeline", "job", "analytics-platform"})

    return sorted(term for term in expanded_terms if len(term) >= 3)


def dedupe_artifacts(artifacts: list[dict]) -> list[dict]:
    # Evita repetir o mesmo artefato quando ele aparece em estrategias de busca diferentes.
    seen = set()
    deduped = []
    for artifact in artifacts:
        key = artifact.get("id") or (
            artifact.get("repo"),
            artifact.get("team"),
            artifact.get("path"),
            artifact.get("block_name"),
            artifact.get("block_start_line"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def fetch_hybrid_results(conn, pergunta: str, embedding: list[float]) -> list[dict]:
    # Combina busca vetorial e lexical para melhorar recall em perguntas naturais.
    vector_rows = []
    lexical_rows = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, repo, team, path, block_name, block_type,
                  block_start_line, block_end_line, summary,
                  tables_ref, columns_ref, content
            FROM artifact_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT 12;
            """,
            (vector_to_pg(embedding),),
        )
        vector_rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    query_terms = extract_query_terms(pergunta)
    if query_terms:
        clauses = []
        params = []
        for term in query_terms[:12]:
            pattern = f"%{term}%"
            clauses.append(
                "(lower(path) LIKE %s OR lower(summary) LIKE %s OR lower(content) LIKE %s OR lower(block_name) LIKE %s)"
            )
            params.extend([pattern, pattern, pattern, pattern])

        sql = f"""
            SELECT id, repo, team, path, block_name, block_type,
                  block_start_line, block_end_line, summary,
                  tables_ref, columns_ref, content
            FROM artifact_chunks
            WHERE {' OR '.join(clauses)}
            LIMIT 12;
        """
        with conn.cursor() as cur:
            cur.execute(sql, params)
            lexical_rows = cur.fetchall()

    artifacts = [dict(zip(cols, row)) for row in vector_rows]
    artifacts.extend(dict(zip(cols, row)) for row in lexical_rows)
    return dedupe_artifacts(artifacts)


def search_artifacts(conn, question: str) -> list[dict]:
    """
    Executa a busca completa a partir da pergunta do usuario, 
    usando embeddings semânticos.
    """
    embeddings_model = BotiEmbeddingsLangChain(
        model="text-embedding-004",
        encoding_format="float",
        task=EmbeddingTask.RETRIEVAL_QUERY.value, 
    )

    print(f"[BUSCA] Gerando embedding semântico para a pergunta: '{question}'")
    
    # embed_query transforma a pergunta numa lista de floats (o embedding de 3072 dims)
    embedding = embeddings_model.embed_query(question)
    
    return fetch_hybrid_results(conn, question, embedding)
