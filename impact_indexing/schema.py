import json
from typing import List, Literal

from pydantic import BaseModel, Field


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


def parse_analysis_response(body: dict) -> dict:
    try:
        message = body["choices"][0]["message"]["content"]
        content = extract_message_content(message)
        return json.loads(content)
    except (KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Resposta inválida do OpenRouter. Corpo recebido: {json.dumps(body)[:2000]}"
        ) from exc

