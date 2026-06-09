import json
import time
import urllib.error
import urllib.request
from typing import Any

from impact_query.config import QuerySettings
from impact_query.context_builder import build_local_report


# --- Funções Auxiliares de Suporte ---

def _parse_llm_message(body: dict) -> str | None:
    """Extrai o conteúdo do texto de forma segura, tratando respostas em string ou listas de blocos."""
    try:
        message = body["choices"][0]["message"]["content"]
        if isinstance(message, str):
            return message
        
        if isinstance(message, list):
            return "".join(
                part.get("text", "") 
                for part in message 
                if isinstance(part, dict) and part.get("type") == "text"
            )
    except (KeyError, IndexError, TypeError):
        pass
    return None


def _extract_retry_delay(exc: urllib.error.HTTPError, error_body: str, default_delay: float) -> float:
    """Tenta extrair o tempo de espera do cabeçalho HTTP ou dos metadados do JSON de erro do OpenRouter."""
    # 1. Tenta pelo cabeçalho padrão HTTP primeiro
    if "Retry-After" in exc.headers:
        try:
            return float(exc.headers["Retry-After"])
        except ValueError:
            pass

    # 2. Tenta raspar a resposta de erro estruturada do OpenRouter
    try:
        error_json = json.loads(error_body)
        metadata = error_json.get("error", {}).get("metadata", {})
        retry_after = (
            metadata.get("retry_after_seconds") or 
            metadata.get("retry_after_seconds_raw")
        )
        if retry_after is not None:
            return float(retry_after)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    return default_delay


# --- Função Principal ---

def call_openrouter_for_report(
    settings: QuerySettings, question: str, context: dict, report: dict
) -> str:
    """Chama o LLM via API OpenRouter utilizando retry exponencial e fallback local em caso de falha."""
    
    # Função interna rápida para padronizar as mensagens de erro com o fallback
    def _fallback_with_msg(reason_msg: str) -> str:
        local_rep = build_local_report(report, question)
        return f"{reason_msg}\n\n{local_rep}"

    if not settings.openrouter_api_key:
        return _fallback_with_msg("OPENROUTER_API_KEY nao configurada. Retornando fallback local.")

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Voce e um analista senior de impacto tecnico. "
                    "Use apenas o contexto fornecido e responda em pt-BR. "
                    "Seja claro, explicativo e objetivo. "
                    "Destaque os times afetados, os arquivos mais importantes, os riscos e o passo a passo recomendado. "
                    "Quando a evidencia for indireta, diga isso explicitamente."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"question": question, "context": context, "report": report}, ensure_ascii=False),
            },
        ],
        "temperature": 0.2,
        "plugins": [{"id": "response-healing"}],
    }

    request = urllib.request.Request(
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

    # Loop de tentativas de requisição
    for attempt in range(1, settings.openrouter_max_retries + 1):
        base_delay = settings.openrouter_retry_delay * attempt
        
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
                
                if parsed_message := _parse_llm_message(body):
                    return parsed_message
                    
                return _fallback_with_msg("OpenRouter respondeu em formato inesperado. Retornando fallback local.")

        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            
            # Se for Rate Limit (429), tenta esperar e continuar o loop
            if exc.code == 429 and attempt < settings.openrouter_max_retries:
                actual_delay = _extract_retry_delay(exc, error_body, default_delay=base_delay)
                time.sleep(actual_delay)
                continue

            return _fallback_with_msg(
                f"OpenRouter respondeu com erro HTTP {exc.code}.\nResposta bruta:\n{error_body}"
            )

        except urllib.error.URLError as exc:
            if attempt < settings.openrouter_max_retries:
                time.sleep(base_delay)
                continue
                
            return _fallback_with_msg(f"Falha de rede ao chamar OpenRouter: {exc.reason}")

    return _fallback_with_msg("OpenRouter falhou apos esgotar todas as tentativas.")