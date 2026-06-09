from pathlib import Path

import joblib
from sklearn.feature_extraction.text import HashingVectorizer

from impact_indexing.config import IndexingSettings
from impact_indexing.openrouter_client import analyze_code_with_openrouter
from impact_indexing.paths import resolve_repo_and_team
from impact_indexing.storage import compute_content_hash


def process_file(settings: IndexingSettings, file_path: Path) -> tuple[list[dict], str, str, str, str]:
    # Processa um unico arquivo e devolve artefatos prontos para persistencia.
    with open(file_path, "r", encoding="utf-8") as f:
        codigo = f.read()

    repo_name, team_name = resolve_repo_and_team(settings.base_dir, file_path)
    rel_path = str(file_path.relative_to(settings.base_dir))
    content_hash = compute_content_hash(codigo)
    dados = analyze_code_with_openrouter(settings, codigo)

    artefatos = []
    for artefato in dados.get("artefatos", []):
        texto_embedding = f"""
        Repositório: {repo_name} | Time: {team_name} | Arquivo: {rel_path}
        Bloco: {artefato['nome']} ({artefato['tipo']})
        Dependências: Tabelas {artefato['tabelas']} | Colunas {artefato['colunas']}
        Resumo de impacto: {artefato['resumo']}
        """.strip()

        artefatos.append(
            {
                "repo": repo_name,
                "team": team_name,
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

    print(f"[INDEX] Processado: {rel_path} ({len(artefatos)} blocos)")
    return artefatos, repo_name, team_name, rel_path, content_hash


def build_embeddings(settings: IndexingSettings, processed_files: list[dict]):
    # Recalcula embeddings apenas para os artefatos desta rodada de indexacao.
    all_artefatos = []
    for entry in processed_files:
        all_artefatos.extend(entry["artefatos"])

    textos = [art["texto_enriquecido"] for art in all_artefatos]
    vectorizer = HashingVectorizer(
        n_features=settings.hash_dim,
        norm=None,
        alternate_sign=False,
    )
    embeddings_matrix = vectorizer.transform(textos).toarray()

    joblib.dump(vectorizer, "hashing_vectorizer.joblib")
    print(f"[INDEX] Vetorizador Hashing salvo com {settings.hash_dim} dimensões.")

    offset = 0
    for entry in processed_files:
        artefatos = entry["artefatos"]
        for index, artefato in enumerate(artefatos):
            artefato["embedding"] = embeddings_matrix[offset + index].tolist()
        offset += len(artefatos)

    return all_artefatos
