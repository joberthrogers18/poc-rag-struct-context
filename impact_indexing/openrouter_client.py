import json
import time
import urllib.error
import urllib.request
from typing import Any

from impact_indexing.config import IndexingSettings
from impact_indexing.schema import build_schema, parse_analysis_response
from genai_sdk.frameworks.langchain.boti_chat_langchain import BotiChatLangChain
from genai_sdk.model_enums import Models

# Cabeçalhos HTTP padrões de Monitoramento da API
HEADER_REMAINING_TOKENS_CAP = "X-RateLimit-Remaining-Tokens"
HEADER_REMAINING_TOKENS_LOWER = "x-ratelimit-remaining-tokens"
HEADER_REMAINING_REQS_CAP = "X-RateLimit-Remaining"
HEADER_REMAINING_REQS_LOWER = "x-ratelimit-remaining"
TOO_MANY_REQUESTS_STATUS = 429

# Limites de Segurança Preventivos (Gargalos)
MIN_SAFE_TOKENS = 15000
MIN_SAFE_REQUESTS = 3

# Tempos de Espera (Delays) em Segundos
DELAY_CRITICAL_RESOURCE = 12.0
DELAY_STANDARD_FALLBACK = 12.0
DELAY_FAST_BURST = 1.5


# Tempos de Espera (Delays) em Segundos
DELAY_FAST_BURST = 1.5


def analyze_code_with_llm(settings: IndexingSettings, code: str) -> dict:
    """Função principal que coordena o fluxo de análise usando LangChain e retentativas."""

    # 1. Instancia o modelo e a ferramenta
    llm = BotiChatLangChain(model=Models.GEMINI, model_name="gemini-2.0-flash")

    # Tool Schema (Mantido como você definiu)
    rag_tool = {
        "type": "function",
        "function": {
            "name": "analyze_code",
            "description": "Analisa um trecho de código e extrai artefatos, dependências e resumo de impacto.",
            "parameters": {
                "type": "object",
                "properties": {
                    "artefatos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "nome": {"type": "string"},
                                "tipo": {"type": "string"},
                                "linha_inicio": {"type": "integer"},
                                "linha_fim": {"type": "integer"},
                                "codigo": {"type": "string"},
                                "tabelas": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "colunas": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "resumo": {"type": "string"},
                            },
                            "required": [
                                "nome",
                                "tipo",
                                "linha_inicio",
                                "linha_fim",
                                "codigo",
                                "tabelas",
                                "colunas",
                                "resumo",
                            ],
                        },
                    },
                },
            },
        },
    }

    prompt = f"""
      Analise o seguinte código ou arquivo de configuração e extraia a lista de artefatos.
      Se for código (JS/TS), extraia funções e classes.
      Se for um esquema de banco de dados (como Prisma), considere cada 'model' ou 'enum' como um artefato distinto.
      Identifique tabelas, colunas, trechos de código exatos e gere o resumo de impacto para cada bloco encontrado.

      Código:
      {code}
    """

    llm_with_tool = llm.bind_tools([rag_tool], tool_choice="analyze_code")

    # 2. Prepara as mensagens
    messages = [
        {
            "role": "system",
            "content": "Você analisa código e sempre responde apenas no schema JSON fornecido, sem texto adicional.",
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    # 3. Executa com o laço de tentativas
    tool_args = _execute_llm_with_retry(settings, llm_with_tool, messages)

    if "artefatos" not in tool_args:
        raise RuntimeError(
            f"Resposta do modelo inválida. Chave 'artefatos' ausente. Recebido: {tool_args}"
        )
        
    return tool_args


def _execute_llm_with_retry(
    settings: IndexingSettings, llm_with_tool: Any, messages: list
) -> dict:
    """Gerencia o laço de tentativas, tratando erros da API e aplicando backoff."""

    # Reaproveitando as configurações de retry do seu settings
    max_retries = getattr(settings, "openrouter_max_retries", 5)
    retry_delay_base = getattr(settings, "openrouter_retry_delay", 5.0)

    for attempt in range(1, max_retries + 1):
        try:
            # Invoca o modelo
            response = llm_with_tool.invoke(messages)

            if getattr(response, "tool_calls", None):
                tool_call = response.tool_calls[0]
                if tool_call["name"] == "analyze_code":

                    # Log de sucesso lendo os metadados (tokens) em vez de headers
                    usage = response.metadata.get("usage_metadata", {})
                    tokens = usage.get("total_token_count", "N/A")
                    print(f"[LLM] Sucesso na análise. Tokens usados: {tokens}")

                    # Pausa preventiva leve para evitar gargalos entre arquivos
                    time.sleep(DELAY_FAST_BURST)
                    return tool_call["args"]

            # Se respondeu mas não usou a tool corretamente, conta como falha de output e tenta de novo
            print(
                f"[LLM] Resposta sem tool_calls na tentativa {attempt}. Retentando..."
            )

        except Exception as exc:
            # O SDK do Boti/Google pode retornar exceções genéricas ou de ResourceExhausted (429)
            error_str = str(exc).lower()

            # Identifica erros de Rate Limit (429) ou Quota
            if any(
                term in error_str
                for term in ["429", "too many requests", "quota", "resourceexhausted"]
            ):
                retry_delay = retry_delay_base * attempt
                print(
                    f"[LLM] Rate limit atingido na tentativa {attempt}/{max_retries}. Aguardando {retry_delay:.1f}s."
                )
                time.sleep(retry_delay)
                continue

            # Outros erros (Rede, Timeout, 500)
            if attempt < max_retries:
                retry_delay = retry_delay_base * attempt
                print(
                    f"[LLM] Falha de rede/API na tentativa {attempt}/{max_retries}. Aguardando {retry_delay:.1f}s. Erro: {exc}"
                )
                time.sleep(retry_delay)
                continue

            raise RuntimeError(
                f"Falha na chamada LLM após esgotar {max_retries} tentativas: {exc}"
            ) from exc

    raise RuntimeError(
        "LLM falhou após esgotar todas as tentativas devido a erros de parsing ou falta de tool_calls."
    )


def analyze_code_with_openrouter(settings: IndexingSettings, codigo: str) -> dict:
    """Função principal que coordena o fluxo de análise e retentativas."""
    if not settings.openrouter_api_key:
        raise RuntimeError(
            "Defina OPENROUTER_API_KEY no ambiente antes de rodar a ingestão."
        )

    request = _prepare_request(settings, codigo)
    body = _execute_with_retry(settings, request)

    if body is None:
        raise RuntimeError(
            "OpenRouter falhou após esgotar todas as tentativas devido a erros de Upstream/Mapeamento."
        )

    return parse_analysis_response(body)


def _prepare_request(settings: IndexingSettings, codigo: str) -> urllib.request.Request:
    """Monta o payload e cria o objeto Request do urllib."""
    prompt = f"""
      Analise o seguinte código e extraia a lista de artefatos (funções, classes, modelos do Prisma).
      Identifique tabelas, colunas, trechos de código exatos e gere o resumo de impacto para cada bloco encontrado.

      Código:
      {codigo}
    """

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {
                "role": "system",
                "content": "Você analisa código e sempre responde apenas no schema JSON fornecido, sem texto adicional.",
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

    return urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "poc-rag-struct-context",
        },
        method="POST",
    )


def _execute_with_retry(
    settings: IndexingSettings, request: urllib.request.Request
) -> dict | None:
    """Gerencia o laço de tentativas, tratando erros de rede e rate limit reativo."""
    for attempt in range(1, settings.openrouter_max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
                used_model = body.get("model", settings.openrouter_model)
                print(f"[OPENROUTER] Modelo utilizado: {used_model}")

                # Controla o ritmo preventivamente baseado nos cabeçalhos de sucesso
                _apply_preventive_rate_limit(response.info())
                return body

        except urllib.error.HTTPError as exc:
            if (
                exc.code == TOO_MANY_REQUESTS_STATUS
                and attempt < settings.openrouter_max_retries
            ):
                _handle_http_429_retry(settings, exc, attempt)
                continue
            raise RuntimeError(
                f"Erro OpenRouter HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}"
            ) from exc

        except urllib.error.URLError as exc:
            if attempt < settings.openrouter_max_retries:
                retry_delay = settings.openrouter_retry_delay * attempt
                print(
                    f"[OPENROUTER] Falha de rede na tentativa {attempt}/{settings.openrouter_max_retries}. Aguardando {retry_delay:.1f}s."
                )
                time.sleep(retry_delay)
                continue
            raise RuntimeError(
                f"Falha de rede ao chamar OpenRouter: {exc.reason}"
            ) from exc

    raise RuntimeError("OpenRouter falhou após esgotar todas as tentativas.")


def _apply_preventive_rate_limit(headers: Any) -> None:
    """Analisa os cabeçalhos de sucesso e aplica uma pausa inteligente preventiva."""
    # Coleta os valores usando as constantes de mapeamento
    remaining_tokens = headers.get(HEADER_REMAINING_TOKENS_CAP) or headers.get(
        HEADER_REMAINING_TOKENS_LOWER
    )
    remaining_requests = headers.get(HEADER_REMAINING_REQS_CAP) or headers.get(
        HEADER_REMAINING_REQS_LOWER
    )

    if remaining_tokens and remaining_requests:
        rem_tokens = int(remaining_tokens)
        rem_reqs = int(remaining_requests)

        print(
            f"[RITMO] Recursos Restantes no Minuto -> Requisições: {rem_reqs} | Tokens: {rem_tokens}"
        )

        # Avalia se atingiu os limites de segurança definidos nas constantes
        if rem_tokens < MIN_SAFE_TOKENS or rem_reqs < MIN_SAFE_REQUESTS:
            print(
                f"[RITMO] Recursos baixos! Aplicando pausa preventiva de {DELAY_CRITICAL_RESOURCE}s..."
            )
            time.sleep(DELAY_CRITICAL_RESOURCE)
        else:
            time.sleep(DELAY_FAST_BURST)
    else:
        print(
            f"[RITMO] Headers de limite ausentes. Aplicando pausa padrão de segurança de {DELAY_STANDARD_FALLBACK}s..."
        )
        time.sleep(DELAY_STANDARD_FALLBACK)


def _handle_http_429_retry(
    settings: IndexingSettings, exc: urllib.error.HTTPError, attempt: int
) -> None:
    """Extrai o tempo de espera do erro 429 e executa a pausa reativa."""
    error_body = exc.read().decode("utf-8", errors="replace")
    retry_delay = settings.openrouter_retry_delay * attempt
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

    print(
        f"[OPENROUTER] Rate limited na tentativa {attempt}/{settings.openrouter_max_retries}. Aguardando {retry_delay:.1f}s."
    )
    time.sleep(retry_delay)
