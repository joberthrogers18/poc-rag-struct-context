import json
import time
import urllib.error
import urllib.request

from impact_indexing.config import IndexingSettings
from impact_indexing.schema import build_schema, parse_analysis_response


def analyze_code_with_openrouter(settings: IndexingSettings, codigo: str) -> dict:
    # Centraliza a chamada ao modelo e aplica retry para uso mais seguro em CI/CD.
    if not settings.openrouter_api_key:
        raise RuntimeError("Defina OPENROUTER_API_KEY no ambiente antes de rodar a ingestão.")

    prompt = f"""Analise o seguinte código e extraia a lista de artefatos (funções, classes, modelos do Prisma).
Identifique tabelas, colunas, trechos de código exatos e gere o resumo de impacto para cada bloco encontrado.

Código:
{codigo}
"""

    payload = {
        "model": settings.openrouter_model,
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
            "Authorization": f"Bearer {settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost",
            "X-Title": "poc-rag-struct-context",
        },
        method="POST",
    )

    body = None
    for attempt in range(1, settings.openrouter_max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
                used_model = body.get("model", settings.openrouter_model)
                print(f"[OPENROUTER] Modelo utilizado: {used_model}")
                break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            retry_delay = settings.openrouter_retry_delay * attempt
            try:
                # Respeita o tempo sugerido pelo provider quando houver rate limit.
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

            if exc.code == 429 and attempt < settings.openrouter_max_retries:
                print(
                    f"[OPENROUTER] Rate limited na tentativa {attempt}/{settings.openrouter_max_retries}. "
                    f"Aguardando {retry_delay:.1f}s."
                )
                time.sleep(retry_delay)
                continue

            raise RuntimeError(
                f"Erro OpenRouter HTTP {exc.code}: {error_body}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < settings.openrouter_max_retries:
                retry_delay = settings.openrouter_retry_delay * attempt
                print(
                    f"[OPENROUTER] Falha de rede na tentativa {attempt}/{settings.openrouter_max_retries}. "
                    f"Aguardando {retry_delay:.1f}s."
                )
                time.sleep(retry_delay)
                continue
            raise RuntimeError(
                f"Falha de rede ao chamar OpenRouter: {exc.reason}"
            ) from exc
    else:
        raise RuntimeError("OpenRouter falhou após esgotar todas as tentativas.")

    if body is None:
        raise RuntimeError(
            "OpenRouter falhou após esgotar todas as tentativas devido a erros de Upstream/Mapeamento."
        )

    return parse_analysis_response(body)
