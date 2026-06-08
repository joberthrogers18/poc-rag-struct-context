import os
import json
import psycopg2
import joblib
from pgvector.psycopg2 import register_vector
from google import genai
from google.genai import types
from dotenv import load_dotenv
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Literal
from sklearn.feature_extraction.text import HashingVectorizer

load_dotenv()

GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
DB_CONN = "dbname=knowledge_base user=admin password=password123 host=localhost"
REPO_NAME = "sample-api"
TEAM_NAME = "application"
BASE_DIR = Path("sample_project")
HASH_DIM=300

client = genai.Client(api_key=GENAI_API_KEY)

class Artefato(BaseModel):
    nome: str = Field(description="Nome da função, classe ou model")
    tipo: Literal["função", "classe", "model"] = Field(description="Tipo do artefato analisado")
    linha_inicio: int = Field(description="Número da primeira linha do bloco baseado no código original")
    linha_fim: int = Field(description="Número da última linha do bloco baseado no código original")
    tabelas: List[str] = Field(description="Lista de tabelas de banco de dados referenciadas")
    colunas: List[str] = Field(description="Lista de colunas do banco de dados referenciadas")
    resumo: str = Field(description="Uma frase explicando o que o bloco faz e seu impacto se quebrar")
    codigo: str = Field(description="O código fonte exato do bloco, sem omissões")

class ResultadoAnalise(BaseModel):
    artefatos: List[Artefato]

def process_file(file_path: Path) -> List[dict]:
    """Extrai artefatos de um arquivo e retorna lista de dicionários com metadados."""
    with open(file_path, 'r', encoding='utf-8') as f:
        codigo = f.read()
    
    rel_path = str(file_path.relative_to(BASE_DIR))
    
    prompt = f"""Analise o seguinte código e extraia a lista de artefatos (funções, classes, modelos do Prisma).
    Identifique tabelas, colunas, trechos de código exatos e gere o resumo de impacto para cada bloco encontrado.
    
    Código:
    {codigo}
    """
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ResultadoAnalise,
            temperature=0.1
        )
    )
    
    dados = json.loads(response.text)
    
    artefatos = []
    for artefato in dados.get('artefatos', []):
        texto_embedding = f"""
        Repositório: {REPO_NAME} | Time: {TEAM_NAME} | Arquivo: {rel_path}
        Bloco: {artefato['nome']} ({artefato['tipo']})
        Dependências: Tabelas {artefato['tabelas']} | Colunas {artefato['colunas']}
        Resumo de impacto: {artefato['resumo']}
        """.strip()
        
        artefatos.append({
            "repo": REPO_NAME,
            "team": TEAM_NAME,
            "path": rel_path,
            "block_name": artefato['nome'],
            "block_type": artefato['tipo'],
            "linha_inicio": artefato['linha_inicio'],
            "linha_fim": artefato['linha_fim'],
            "codigo": artefato['codigo'],
            "tabelas": artefato['tabelas'],
            "colunas": artefato['colunas'],
            "resumo": artefato['resumo'],
            "texto_enriquecido": texto_embedding
        })
    
    print(f"Processado: {rel_path} ({len(artefatos)} blocos)")
    return artefatos

if __name__ == "__main__":
    todos_artefatos = []
    
    # Extrai artefatos de todos os arquivos
    for file_path in BASE_DIR.rglob("*"):
        if file_path.is_file() and file_path.suffix in ['.js', '.ts', '.prisma']:
            todos_artefatos.extend(process_file(file_path))
    
    if not todos_artefatos:
        print("Nenhum artefato encontrado. Encerrando.")
        exit()
    
    # Cria o vetorizador Hashing com todos os textos enriquecidos
    textos = [art["texto_enriquecido"] for art in todos_artefatos]
    
    vectorizer = HashingVectorizer(n_features=HASH_DIM, norm=None, alternate_sign=False)
    embeddings_matrix = vectorizer.transform(textos).toarray()
    
    # Salva o vetorizador para uso nas buscas
    joblib.dump(vectorizer, "hashing_vectorizer.joblib")
    print(f"Vetorizador Hashing salvo. Vocabulário: {len(vectorizer.get_feature_names_out())} palavras.")
    
    # 4. Conecta ao banco e insere
    conn = psycopg2.connect(DB_CONN)
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    conn.commit()
    register_vector(conn)
    
    with conn.cursor() as cur:
        for i, art in enumerate(todos_artefatos):
            embedding_list = embeddings_matrix[i].tolist()
            cur.execute("""
                INSERT INTO artifact_chunks 
                (repo, team, path, block_name, block_type, block_start_line, block_end_line, content, tables_ref, columns_ref, summary, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                art["repo"], art["team"], art["path"], art["block_name"], art["block_type"],
                art["linha_inicio"], art["linha_fim"], art["codigo"],
                art["tabelas"], art["colunas"], art["resumo"], embedding_list
            ))
    
    conn.commit()
    conn.close()
    print(f"Ingestão concluída! {len(todos_artefatos)} blocos inseridos no banco.")