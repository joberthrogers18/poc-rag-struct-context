import json
from typing import List, Literal

from pydantic import BaseModel, Field


class Artifacts(BaseModel):
    name: str = Field(description="Nome da função, classe ou model")
    type: Literal["função", "classe", "model"] = Field(
        description="Tipo do artefato analisado"
    )
    start_line: int = Field(
        description="Número da primeira linha do bloco baseado no código original"
    )
    end_line: int = Field(
        description="Número da última linha do bloco baseado no código original"
    )
    tables: List[str] = Field(
        description="Lista de tabelas de banco de dados referenciadas"
    )
    columns: List[str] = Field(
        description="Lista de colunas do banco de dados referenciadas"
    )
    summary: str = Field(
        description="Uma frase explicando o que o bloco faz e seu impacto se quebrar"
    )
    code: str = Field(description="O código fonte exato do bloco, sem omissões")


class AnalysisResult(BaseModel):
    artifacts: List[Artifacts]


def build_schema() -> dict:
    # Gera o schema JSON esperado pelo modelo com compatibilidade para Pydantic 1 e 2.
    if hasattr(AnalysisResult, "model_json_schema"):
        return AnalysisResult.model_json_schema()
    return AnalysisResult.schema()


def extract_message_content(message_content) -> str:
    # Normaliza o formato da resposta do provider para uma string JSON consumivel.
    if isinstance(message_content, str):
        return message_content

    if isinstance(message_content, list):
        text_parts = []
        for part in message_content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_parts.append(part.get("text", ""))
        return "".join(text_parts)

    raise ValueError("Formato de resposta inesperado ao ler o conteúdo do modelo.")


def parse_analysis_response(body: dict) -> dict:
    # Valida e desserializa a resposta do modelo para o formato interno do indexador.
    try:
        message = body["choices"][0]["message"]["content"]
        content = extract_message_content(message)
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Resposta inválida do Modelo. Corpo recebido: {json.dumps(body)[:2000]}"
        ) from exc
