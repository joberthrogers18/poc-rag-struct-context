from pathlib import Path

import joblib
from sklearn.feature_extraction.text import HashingVectorizer

from impact_indexing.config import IndexingSettings
from impact_indexing.openrouter_client import analyze_code_with_llm
from impact_indexing.paths import resolve_repo_and_team
from impact_indexing.storage import compute_content_hash, check_hash_exists
from genai_sdk.frameworks.langchain.boti_embeddings_langchain import (
    BotiEmbeddingsLangChain,
)
from genai_sdk.model_enums import EmbeddingTask
import time


def process_file(
    conn, settings: IndexingSettings, file_path: Path
) -> tuple[list[dict], str, str, str, str]:
    # Processa um unico arquivo e devolve artefatos prontos para persistencia.
    with open(file_path, "r", encoding="utf-8") as f:
        codigo = f.read()

    repo_name, team_name = resolve_repo_and_team(settings.base_dir, file_path)
    rel_path = str(file_path.relative_to(settings.base_dir))
    content_hash = compute_content_hash(codigo)

    if check_hash_exists(conn, content_hash):
        print(f"[INDEX] Pulando {rel_path} (hash inalterado)")
        return [], repo_name, team_name, rel_path, content_hash

    dados = analyze_code_with_llm(settings, codigo)

    print(
        "[Aviso] Aguardando 2 segundos para limpar a janela de requisições do modelo..."
    )
    time.sleep(2)

    artifacts = []
    for artifact in dados.get("artefatos", []):
        texto_embedding = f"""
        Repositório: {repo_name} | Time: {team_name} | Arquivo: {rel_path}
        Bloco: {artifact['nome']} ({artifact['tipo']})
        Dependências: Tabelas {artifact['tabelas']} | Colunas {artifact['colunas']}
        Resumo de impacto: {artifact['resumo']}
        """.strip()

        artifacts.append(
            {
                "repo": repo_name,
                "team": team_name,
                "path": rel_path,
                "block_name": artifact["nome"],
                "block_type": artifact["tipo"],
                "linha_inicio": artifact["linha_inicio"],
                "linha_fim": artifact["linha_fim"],
                "codigo": artifact["codigo"],
                "tabelas": artifact["tabelas"],
                "colunas": artifact["colunas"],
                "resumo": artifact["resumo"],
                "texto_enriquecido": texto_embedding,
            }
        )

    print(f"[INDEX] Processado: {rel_path} ({len(artifacts)} blocos)")
    return artifacts, repo_name, team_name, rel_path, content_hash


def build_embeddings(processed_files: list[dict]):
    """
    Gera embeddings semânticos para os artefatos usando o GenAI SDK (BotiEmbeddingsLangChain).
    """

    all_artifacts = []
    for entry in processed_files:
        all_artifacts.extend(entry["artefatos"])

    # Extrai os textos
    texts = [art["texto_enriquecido"] for art in all_artifacts]

    # Inicializa o modelo de embeddings do SDK do Boti
    embeddings_model = BotiEmbeddingsLangChain(
        model="text-embedding-004",
        encoding_format="float",
        task=EmbeddingTask.RETRIEVAL_DOCUMENT.value
    )

    print(f"[INDEX] Gerando embeddings para {len(texts)} artefatos via GenAI SDK...")

    # embed_documents processa a lista de textos e devolve list[list[float]]
    embeddings_matrix = embeddings_model.embed_documents(texts)

    # Verifica o tamanho da dimensão do embedding retornado apenas para log
    dim_size = len(embeddings_matrix[0]) if embeddings_matrix else 0
    print(f"[INDEX] Embeddings semânticos gerados com sucesso. (Dimensões: {dim_size})")

    # Mapeia de volta para os artefatos
    offset = 0
    for entry in processed_files:
        artifacts = entry["artefatos"]
        for index, artifact in enumerate(artifacts):
            # Os embeddings já vêm no formato de lista de floats
            artifact["embedding"] = embeddings_matrix[offset + index]
        offset += len(artifacts)

    return all_artifacts
