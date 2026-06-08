import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Literal

import joblib
import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import HashingVectorizer

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
DB_CONN = "dbname=knowledge_base user=admin password=password123 host=localhost"
REPO_NAME = "sample-api"
TEAM_NAME = "application"
BASE_DIR = Path("sample_project")
HASH_DIM = 384
OPENROUTER_MAX_RETRIES = int(os.getenv("OPENROUTER_MAX_RETRIES", "5"))
OPENROUTER_RETRY_DELAY = float(os.getenv("OPENROUTER_RETRY_DELAY", "5"))


class Artefato(BaseModel):
    nome: str = Field(description="Nome da função, classe ou model")
    tipo: Literal["função", "classe", "model"] = Field(
        description="Tipo do artefato analisado"
    )
    linha_inicio: int = Field(
        description="Número da primeira linha do bloco baseado no código original"
    )
    linha_fim: int = Field(
        description="Número da última linha do bloco baseado no código original"
    )
    tabelas: List[str] = Field(
        description="Lista de tabelas de banco de dados referenciadas"
    )
    colunas: List[str] = Field(
        description="Lista de colunas do banco de dados referenciadas"
    )
    resumo: str = Field(
        description="Uma frase explicando o que o bloco faz e seu impacto se quebrar"
    )
    codigo: str = Field(description="O código fonte exato do bloco, sem omissões")


class ResultadoAnalise(BaseModel):
    artefatos: List[Artefato]


def build_schema() -> dict:
    if hasattr(ResultadoAnalise, "model_json_schema"):
        return ResultadoAnalise.model_json_schema()
    return ResultadoAnalise.schema()


def extract_message_content(message_content) -> str:
    if isinstance(message_content, str):
        return message_content

    if isinstance(message_content, list):
        text_parts = []
        for part in message_content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return "".join(text_parts)

    raise ValueError("Formato de resposta inesperado ao ler o conteúdo do modelo.")


def analyze_code_with_openrouter(codigo: str) -> dict:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("Defina OPENROUTER_API_KEY no ambiente antes de rodar a ingestão.")

    prompt = f"""Analise o seguinte código e extraia a lista de artefatos (funções, classes, modelos do Prisma).
Identifique tabelas, colunas, trechos de código exatos e gere o resumo de impacto para cada bloco encontrado.

Código:
{codigo}
"""

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Você analisa código e sempre responde apenas no schema JSON "
                    "fornecido, sem texto adicional."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "resultado_analise",
                "strict": True,
                "schema": build_schema(),
            },
        },
        "plugins": [{"id": "response-healing"}],
    }

    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "poc-rag-struct-context",
        },
        method="POST",
    )

    for attempt in range(1, OPENROUTER_MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
                used_model = body.get("model", OPENROUTER_MODEL)
                print(f"OpenRouter respondeu com modelo: {used_model}")
                break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            retry_delay = OPENROUTER_RETRY_DELAY * attempt

            try:
                error_json = json.loads(error_body)
                metadata = error_json.get("error", {}).get("metadata", {})
                retry_delay = float(
                    metadata.get("retry_after_seconds")
                    or metadata.get("retry_after_seconds_raw")
                    or exc.headers.get("Retry-After")
                    or retry_delay
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            if exc.code == 429 and attempt < OPENROUTER_MAX_RETRIES:
                print(
                    f"OpenRouter rate limited (tentativa {attempt}/{OPENROUTER_MAX_RETRIES}). "
                    f"Aguardando {retry_delay:.1f}s para tentar de novo."
                )
                time.sleep(retry_delay)
                continue

            raise RuntimeError(
                f"Erro OpenRouter HTTP {exc.code}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < OPENROUTER_MAX_RETRIES:
                retry_delay = OPENROUTER_RETRY_DELAY * attempt
                print(
                    f"Falha de rede ao chamar OpenRouter (tentativa {attempt}/{OPENROUTER_MAX_RETRIES}). "
                    f"Aguardando {retry_delay:.1f}s."
                )
                time.sleep(retry_delay)
                continue
            raise RuntimeError(
                f"Falha de rede ao chamar OpenRouter: {exc.reason}"
            ) from exc
    else:
        raise RuntimeError("OpenRouter falhou após esgotar todas as tentativas.")

    try:
        message = body["choices"][0]["message"]["content"]
        content = extract_message_content(message)
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Resposta inválida do OpenRouter. Corpo recebido: {json.dumps(body)[:2000]}"
        ) from exc


def process_file(file_path: Path) -> List[dict]:
    """Extrai artefatos de um arquivo e retorna lista de dicionários com metadados."""
    with open(file_path, "r", encoding="utf-8") as f:
        codigo = f.read()

    rel_path = str(file_path.relative_to(BASE_DIR))
    dados = analyze_code_with_openrouter(codigo)

    artefatos = []
    for artefato in dados.get("artefatos", []):
        texto_embedding = f"""
        Repositório: {REPO_NAME} | Time: {TEAM_NAME} | Arquivo: {rel_path}
        Bloco: {artefato['nome']} ({artefato['tipo']})
        Dependências: Tabelas {artefato['tabelas']} | Colunas {artefato['colunas']}
        Resumo de impacto: {artefato['resumo']}
        """.strip()

        artefatos.append(
            {
                "repo": REPO_NAME,
                "team": TEAM_NAME,
                "path": rel_path,
                "block_name": artefato["nome"],
                "block_type": artefato["tipo"],
                "linha_inicio": artefato["linha_inicio"],
                "linha_fim": artefato["linha_fim"],
                "codigo": artefato["codigo"],
                "tabelas": artefato["tabelas"],
                "colunas": artefato["colunas"],
                "resumo": artefato["resumo"],
                "texto_enriquecido": texto_embedding,
            }
        )

    print(f"Processado: {rel_path} ({len(artefatos)} blocos)")
    return artefatos


def main():
    todos_artefatos = []

    for file_path in BASE_DIR.rglob("*"):
        if file_path.is_file() and file_path.suffix in [".js", ".ts", ".prisma"]:
            todos_artefatos.extend(process_file(file_path))

    if not todos_artefatos:
        print("Nenhum artefato encontrado. Encerrando.")
        sys.exit(0)

    textos = [art["texto_enriquecido"] for art in todos_artefatos]
    vectorizer = HashingVectorizer(
        n_features=HASH_DIM,
        norm=None,
        alternate_sign=False,
    )
    embeddings_matrix = vectorizer.transform(textos).toarray()

    joblib.dump(vectorizer, "hashing_vectorizer.joblib")
    print(f"Vetorizador Hashing salvo com {HASH_DIM} dimensões.")

    conn = psycopg2.connect(DB_CONN)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()
    register_vector(conn)

    with conn.cursor() as cur:
        for i, art in enumerate(todos_artefatos):
            embedding_list = embeddings_matrix[i].tolist()
            cur.execute(
                """
                INSERT INTO artifact_chunks
                (repo, team, path, block_name, block_type, block_start_line, block_end_line, content, tables_ref, columns_ref, summary, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    art["repo"],
                    art["team"],
                    art["path"],
                    art["block_name"],
                    art["block_type"],
                    art["linha_inicio"],
                    art["linha_fim"],
                    art["codigo"],
                    art["tabelas"],
                    art["colunas"],
                    art["resumo"],
                    embedding_list,
                ),
            )

    conn.commit()
    conn.close()
    print(f"Ingestão concluída! {len(todos_artefatos)} blocos inseridos no banco.")


if __name__ == "__main__":
    main()
