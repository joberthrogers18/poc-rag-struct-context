import os
from typing import List, Optional
from pathlib import Path

import joblib
import psycopg2
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from sklearn.feature_extraction.text import HashingVectorizer

load_dotenv()

DB_CONN = os.getenv("DB_CONN", "dbname=knowledge_base user=admin password=password123 host=localhost")
HASH_DIM = int(os.getenv("HASH_DIM", "300"))
VECTORIZER_PATH = os.getenv("VECTORIZER_PATH", "hashing_vectorizer.joblib")

app = FastAPI(title="MCP - Artifact Access")

class Artifact(BaseModel):
    id: Optional[int]
    repo: Optional[str]
    team: Optional[str]
    path: Optional[str]
    block_name: Optional[str]
    block_type: Optional[str]
    block_start_line: Optional[int]
    block_end_line: Optional[int]
    content: Optional[str]
    tables_ref: Optional[List[str]]
    columns_ref: Optional[List[str]]
    summary: Optional[str]


def vector_to_pg(value: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in value) + "]"


def load_vectorizer() -> HashingVectorizer:
    if not Path(VECTORIZER_PATH).exists():
        raise FileNotFoundError(f"Vetorizador não encontrado em {VECTORIZER_PATH}")
    vec = joblib.load(VECTORIZER_PATH)
    return vec


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/search", response_model=List[Artifact])
def search(q: str = Query(..., min_length=1), top_k: int = Query(5, ge=1, le=100)):
    """Busca por similaridade usando o vetorizador Hashing e consulta no Postgres (pgvector).
    Retorna os top_k artefatos mais próximos.
    """
    try:
        vectorizer = load_vectorizer()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Vetoriza a query
    q_vec = vectorizer.transform([q]).toarray()[0].tolist()

    try:
        conn = psycopg2.connect(DB_CONN)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar ao banco: {e}")

    try:
        register_stmt = "CREATE EXTENSION IF NOT EXISTS vector;"
        with conn.cursor() as cur:
            cur.execute(register_stmt)
        conn.commit()
    except Exception:
        # ignore if extension already exists or permission issues
        pass

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, repo, team, path, block_name, block_type, block_start_line, block_end_line,
                       content, tables_ref, columns_ref, summary
                FROM artifact_chunks
                ORDER BY embedding <-> %s::vector
                LIMIT %s
                """,
                (vector_to_pg(q_vec), top_k),
            )
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Erro na query: {e}")

    conn.close()

    results: List[Artifact] = []
    for row in rows:
        row_dict = dict(zip(cols, row))
        # normalize keys to match Artifact model
        art = Artifact(
            id=row_dict.get('id'),
            repo=row_dict.get('repo'),
            team=row_dict.get('team'),
            path=row_dict.get('path'),
            block_name=row_dict.get('block_name'),
            block_type=row_dict.get('block_type'),
            block_start_line=row_dict.get('block_start_line'),
            block_end_line=row_dict.get('block_end_line'),
            content=row_dict.get('content'),
            tables_ref=row_dict.get('tables_ref'),
            columns_ref=row_dict.get('columns_ref'),
            summary=row_dict.get('summary'),
        )
        results.append(art)

    return results


@app.get("/artifact/{artifact_id}", response_model=Artifact)
def get_artifact(artifact_id: int):
    try:
        conn = psycopg2.connect(DB_CONN)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao conectar ao banco: {e}")

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, repo, team, path, block_name, block_type, block_start_line, block_end_line, content, tables_ref, columns_ref, summary FROM artifact_chunks WHERE id = %s",
                (artifact_id,)
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Artefato não encontrado")
            cols = [desc[0] for desc in cur.description]
            row_dict = dict(zip(cols, row))
    except HTTPException:
        conn.close()
        raise
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Erro na query: {e}")

    conn.close()

    art = Artifact(
        id=row_dict.get('id'),
        repo=row_dict.get('repo'),
        team=row_dict.get('team'),
        path=row_dict.get('path'),
        block_name=row_dict.get('block_name'),
        block_type=row_dict.get('block_type'),
        block_start_line=row_dict.get('block_start_line'),
        block_end_line=row_dict.get('block_end_line'),
        content=row_dict.get('content'),
        tables_ref=row_dict.get('tables_ref'),
        columns_ref=row_dict.get('columns_ref'),
        summary=row_dict.get('summary'),
    )
    return art


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
