import os
import json
import re
import time
import urllib.error
import urllib.request
import joblib
import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector

from mcp_framework import FastMCP

load_dotenv()

DEFAULT_VECTORIZER_PATH = "hashing_vectorizer.joblib"
LEGACY_VECTORIZER_PATH = "tfidf_vectorizer.joblib"
VECTORIZER_PATH = os.getenv("VECTORIZER_PATH", DEFAULT_VECTORIZER_PATH)
DB_CONN = os.getenv("DB_CONN", "dbname=knowledge_base user=admin password=password123 host=localhost")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
OPENROUTER_MAX_RETRIES = int(os.getenv("OPENROUTER_MAX_RETRIES", "5"))
OPENROUTER_RETRY_DELAY = float(os.getenv("OPENROUTER_RETRY_DELAY", "5"))

if not os.path.exists(VECTORIZER_PATH):
    if VECTORIZER_PATH == DEFAULT_VECTORIZER_PATH and os.path.exists(LEGACY_VECTORIZER_PATH):
        VECTORIZER_PATH = LEGACY_VECTORIZER_PATH
    else:
        raise FileNotFoundError(
            f"Vetorizador não encontrado em {VECTORIZER_PATH}. "
            f"Rode o ingest.py para gerar {DEFAULT_VECTORIZER_PATH} "
            f"ou defina VECTORIZER_PATH explicitamente."
        )

vectorizer = joblib.load(VECTORIZER_PATH)

mcp = FastMCP("ImpactAnalyzer")


def vector_to_pg(value: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in value) + "]"


def format_list(items: list[str], empty_message: str) -> str:
    if not items:
        return empty_message
    return ", ".join(items)


def estimate_risk(files_count: int, columns_count: int, etl_count: int) -> str:
    if files_count >= 5 or etl_count > 0:
        return "alto"
    if files_count >= 3 or columns_count >= 2:
        return "medio"
    return "baixo"


def extract_query_terms(pergunta: str) -> list[str]:
    base_terms = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", (pergunta or "").lower()))

    expanded_terms = set(base_terms)
    if {"usuario", "usuários", "usuarios", "user"} & base_terms:
        expanded_terms.update({"user", "users", "customer-api"})
    if {"criados", "criacao", "criação", "recentemente", "recentes", "recent"} & base_terms:
        expanded_terms.update(
            {
                "createdat",
                "created_at",
                "createdafter",
                "createdAfter",
                "signupdate",
                "snapshot",
                "recent",
                "recentes",
            }
        )
    if {"consome", "consumem", "consumo", "usa", "usam"} & base_terms:
        expanded_terms.update(
            {
                "pipeline",
                "job",
                "export",
                "snapshot",
                "sourceReference",
                "send",
            }
        )
    if {"etl", "dados", "data", "analytics"} & base_terms:
        expanded_terms.update({"etl", "pipeline", "job", "warehouse", "analytics-platform"})

    return sorted(term for term in expanded_terms if len(term) >= 3)


def dedupe_artifacts(artifacts: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for artifact in artifacts:
        key = artifact.get("id") or (
            artifact.get("repo"),
            artifact.get("team"),
            artifact.get("path"),
            artifact.get("block_name"),
            artifact.get("block_start_line"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def fetch_hybrid_results(conn, pergunta: str, embedding: list[float]) -> list[dict]:
    vector_rows = []
    lexical_rows = []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, repo, team, path, block_name, block_type,
                   block_start_line, block_end_line, summary,
                   tables_ref, columns_ref, content
            FROM artifact_chunks
            ORDER BY embedding <-> %s::vector
            LIMIT 12;
            """,
            (vector_to_pg(embedding),),
        )
        vector_rows = cur.fetchall()
        cols = [d[0] for d in cur.description]

    query_terms = extract_query_terms(pergunta)
    if query_terms:
        clauses = []
        params = []
        for term in query_terms[:12]:
            pattern = f"%{term}%"
            clauses.append(
                "(lower(path) LIKE %s OR lower(summary) LIKE %s OR lower(content) LIKE %s OR lower(block_name) LIKE %s)"
            )
            params.extend([pattern, pattern, pattern, pattern])

        sql = f"""
            SELECT id, repo, team, path, block_name, block_type,
                   block_start_line, block_end_line, summary,
                   tables_ref, columns_ref, content
            FROM artifact_chunks
            WHERE {' OR '.join(clauses)}
            LIMIT 12;
        """
        with conn.cursor() as cur:
            cur.execute(sql, params)
            lexical_rows = cur.fetchall()

    artifacts = [dict(zip(cols, row)) for row in vector_rows]
    artifacts.extend(dict(zip(cols, row)) for row in lexical_rows)
    return dedupe_artifacts(artifacts)


def build_llm_context(report: dict, pergunta: str, artifacts: list[dict]) -> dict:
    files_count = len(report["files_affected"])
    columns_count = len(report["columns_affected"])
    etl_count = len(report["etl_candidates"])
    risk = estimate_risk(files_count, columns_count, etl_count)

    key_artifacts = []
    for artifact in artifacts[:5]:
        key_artifacts.append(
            {
                "id": artifact.get("id"),
                "path": artifact.get("path"),
                "block_name": artifact.get("block_name"),
                "block_type": artifact.get("block_type"),
                "summary": artifact.get("summary"),
                "tables_ref": artifact.get("tables_ref") or [],
                "columns_ref": artifact.get("columns_ref") or [],
                "content_excerpt": (artifact.get("content") or "")[:1200],
            }
        )

    return {
        "user_request": pergunta,
        "analysis_summary": {
            "estimated_risk": risk,
            "files_count": files_count,
            "columns_count": columns_count,
            "etl_count": etl_count,
            "has_direct_column_match": bool(report["columns_affected"]),
            "has_possible_etl_impact": bool(report["etl_candidates"]),
        },
        "impact_map": {
            "files_affected": report["files_affected"],
            "teams_affected": report["teams_affected"],
            "tables_affected": report["tables_affected"],
            "columns_affected": report["columns_affected"],
            "etl_candidates": report["etl_candidates"],
        },
        "recommended_checks": report["suggested_actions"],
        "artifact_summaries": report["artifact_summaries"][:8],
        "key_artifacts": key_artifacts,
        "response_requirements": {
            "language": "pt-BR",
            "tone": "claro, tecnico e amigavel",
            "sections": [
                "resumo executivo",
                "impactos mais provaveis",
                "arquivos e componentes que merecem revisao",
                "como executar a mudanca com seguranca",
                "riscos e validacoes antes do deploy",
            ],
            "must_ground_on_context": True,
            "avoid_generic_advice": True,
        },
    }


def call_openrouter_for_report(question: str, context: dict, report: dict) -> str:
    if not OPENROUTER_API_KEY:
        return (
            "OPENROUTER_API_KEY nao configurada. Retornando fallback local.\n\n"
            + build_local_report(report, question)
        )

    payload = {
        "model": OPENROUTER_MODEL,
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
                "content": json.dumps(
                    {
                        "question": question,
                        "context": context,
                        "report": report,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "temperature": 0.2,
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
                message = body["choices"][0]["message"]["content"]
                if isinstance(message, str):
                    return message
                if isinstance(message, list):
                    text_parts = []
                    for part in message:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    if text_parts:
                        return "".join(text_parts)
                return (
                    "OpenRouter respondeu em formato inesperado. Retornando fallback local.\n\n"
                    + build_local_report(report, question)
                )
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
                time.sleep(retry_delay)
                continue

            return (
                f"OpenRouter respondeu com erro HTTP {exc.code}.\n"
                f"Resposta bruta:\n{error_body}\n\n"
                f"Fallback local:\n\n{build_local_report(report, question)}"
            )
        except urllib.error.URLError as exc:
            if attempt < OPENROUTER_MAX_RETRIES:
                time.sleep(OPENROUTER_RETRY_DELAY * attempt)
                continue
            return (
                f"Falha de rede ao chamar OpenRouter: {exc.reason}\n\n"
                f"Fallback local:\n\n{build_local_report(report, question)}"
            )

    return (
        "OpenRouter falhou apos esgotar todas as tentativas.\n\n"
        + build_local_report(report, question)
    )


def build_local_report(report: dict, pergunta: str = None) -> str:
    files_count = len(report["files_affected"])
    columns_count = len(report["columns_affected"])
    etl_count = len(report["etl_candidates"])
    risk = estimate_risk(files_count, columns_count, etl_count)

    lines = []
    lines.append("Relatorio de impacto")
    if pergunta:
        lines.append(f"Solicitacao analisada: {pergunta}")

    if not report["artifact_summaries"]:
        lines.append("")
        lines.append("Resumo executivo:")
        lines.append(
            "Nao encontrei artefatos relevantes para responder com confianca. "
            "Isso normalmente indica que a base ainda nao foi ingerida por completo "
            "ou que a pergunta esta generica demais."
        )
        lines.append("")
        lines.append("Proximos passos:")
        lines.append("1. Rode o ingest.py novamente para atualizar a base vetorial.")
        lines.append("2. Confirme se a tabela artifact_chunks recebeu registros.")
        lines.append("3. Refaca a pergunta incluindo nome da tabela, coluna ou arquivo.")
        return "\n".join(lines)

    lines.append("")
    lines.append("Resumo executivo:")
    lines.append(
        f"A solicitacao parece ter risco {risk}, considerando {files_count} arquivo(s) relacionado(s), "
        f"{columns_count} coluna(s) mencionada(s) e {etl_count} possivel(is) integracao(oes) dependente(s)."
    )
    if report["columns_affected"]:
        lines.append(
            "Os principais pontos de atencao estao nas colunas: "
            + format_list(report["columns_affected"], "nenhuma coluna identificada")
            + "."
        )
    else:
        lines.append(
            "Nao houve correspondencia direta de colunas, entao a validacao manual dos arquivos retornados continua importante."
        )

    lines.append("")
    lines.append("Impacto identificado:")
    lines.append(
        "Times afetados: "
        + format_list(report["teams_affected"], "nenhum time identificado")
    )
    lines.append(
        "Arquivos afetados: "
        + format_list(report["files_affected"], "nenhum arquivo identificado")
    )
    lines.append(
        "Tabelas afetadas: "
        + format_list(report["tables_affected"], "nenhuma tabela identificada")
    )
    lines.append(
        "Colunas afetadas: "
        + format_list(report["columns_affected"], "nenhuma coluna identificada")
    )
    if report["etl_candidates"]:
        lines.append(
            "Possiveis ETLs ou jobs afetados: "
            + format_list(report["etl_candidates"], "nenhum fluxo identificado")
        )

    lines.append("")
    lines.append("Artefatos mais relevantes:")
    for summary in report["artifact_summaries"][:5]:
        lines.append(
            f"- [{summary.get('id')}] {summary.get('path')}: {summary.get('summary') or 'Sem resumo disponivel.'}"
        )

    lines.append("")
    lines.append("Como eu seguiria:")
    lines.append("1. Validaria onde esse campo aparece no schema, repositorio e camada de servico.")
    lines.append("2. Conferiria leituras, escritas, filtros, ordenacoes e serializacao antes de remover.")
    if report["etl_candidates"]:
        lines.append("3. Revisaria os jobs ou pipelines detectados para evitar quebra em carga ou transformacao.")
        lines.append("4. So depois removeria a coluna do banco e ajustaria migracoes, testes e contratos.")
    else:
        lines.append("3. So depois removeria a coluna do banco e ajustaria migracoes, testes e contratos.")

    if report["suggested_actions"]:
        lines.append("")
        lines.append("Checagens sugeridas:")
        for action in report["suggested_actions"]:
            lines.append(f"- {action}")

    return "\n".join(lines)


@mcp.tool()
def buscar_impacto_codigo(pergunta: str) -> str:
    """Busca os artefatos mais parecidos com a pergunta usando o vetorizador salvo.

    Retorna uma string JSON com os resultados.
    """
    embedding = vectorizer.transform([pergunta]).toarray()[0].tolist()

    conn = psycopg2.connect(DB_CONN)
    try:
        register_vector(conn)
    except Exception:
        # ignore if extension already registered
        pass

    resultados = fetch_hybrid_results(conn, pergunta, embedding)
    conn.close()
    return json.dumps(resultados, ensure_ascii=False)


@mcp.tool()
def gerar_relatorio_impacto(ids: list = None, pergunta: str = None) -> str:
    """Gera um relatório de impacto a partir de uma lista de artefato `ids` ou de uma `pergunta`.

    O relatório agrega tabelas, colunas, arquivos afetados e detecta possíveis ETLs.
    Se a variável de ambiente `LLM_ENDPOINT` estiver configurada, o payload será enviado
    para esse endpoint (POST JSON) e o texto retornado será usado como relatório final.
    Caso contrário, é retornado um resumo gerado localmente.
    """
    if ids is None and pergunta is None:
        return json.dumps({"error": "Informe 'ids' ou 'pergunta'"}, ensure_ascii=False)

    conn = psycopg2.connect(DB_CONN)
    try:
        register_vector(conn)
    except Exception:
        pass

    artifacts = []
    cols = []

    if ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, repo, team, path, block_name, block_type, block_start_line, block_end_line, summary, tables_ref, columns_ref, content FROM artifact_chunks WHERE id = ANY(%s)",
                (ids,)
            )
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            artifacts.extend([dict(zip(cols, r)) for r in rows])
    else:
        # usar busca por pergunta para obter artefatos iniciais
        resultados_json = buscar_impacto_codigo(pergunta)
        try:
            resultados = json.loads(resultados_json)
            artifacts.extend(dedupe_artifacts(resultados))
        except Exception:
            pass

    # tenta buscar relations (se existir tabela artifact_relations)
    related = []
    try:
        with conn.cursor() as cur:
            ids_to_check = [a.get('id') for a in artifacts if a.get('id')]
            if ids_to_check:
                cur.execute(
                    "SELECT related_id FROM artifact_relations WHERE artifact_id = ANY(%s)",
                    (ids_to_check,)
                )
                rel_rows = cur.fetchall()
                for r in rel_rows:
                    related.append(r[0])
                if related:
                    cur.execute(
                        "SELECT id, repo, team, path, block_name, block_type, block_start_line, block_end_line, summary, tables_ref, columns_ref, content FROM artifact_chunks WHERE id = ANY(%s)",
                        (related,)
                    )
                    rows = cur.fetchall()
                    cols = [d[0] for d in cur.description]
                    artifacts.extend([dict(zip(cols, r)) for r in rows])
    except Exception:
        # tabela de relações pode não existir — ignora
        pass

    conn.close()
    artifacts = dedupe_artifacts(artifacts)

    # agrega informações
    teams = set()
    tables = set()
    columns = set()
    files = set()
    etl_files = set()
    summaries = []

    for a in artifacts:
        if a.get('team'):
            teams.add(a.get('team'))
        for t in (a.get('tables_ref') or []):
            tables.add(t)
        for c in (a.get('columns_ref') or []):
            columns.add(c)
        if a.get('path'):
            files.add(a.get('path'))
            p = a.get('path').lower()
            if any(x in p for x in ['etl', 'pipeline', 'jobs', 'airflow', 'dag', 'dbt']):
                etl_files.add(a.get('path'))
        summaries.append({'id': a.get('id'), 'path': a.get('path'), 'summary': a.get('summary')})

    report = {
        'teams_affected': sorted(list(teams)),
        'tables_affected': sorted(list(tables)),
        'columns_affected': sorted(list(columns)),
        'files_affected': sorted(list(files)),
        'etl_candidates': sorted(list(etl_files)),
        'artifact_summaries': summaries,
        'suggested_actions': []
    }

    # heurísticas simples de sugestão
    if columns:
        for col in sorted(columns):
            report['suggested_actions'].append(f"Revisar uso da coluna '{col}' em {len(files)} arquivos; avaliar impacto antes de remover.")

    if etl_files:
        report['suggested_actions'].append(f"Arquivos/ETLs detectados: {', '.join(sorted(etl_files))}. Verificar jobs de ingestão/transformação.")

    # Se houver endpoint LLM configurado, envie o prompt para obter relatório final
    llm_context = build_llm_context(report, pergunta, artifacts)
    return call_openrouter_for_report(pergunta, llm_context, report)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=False, help="tool name to call")
    parser.add_argument("question", nargs="?", help="question text")
    args = parser.parse_args()

    if args.tool:
        if args.tool == "gerar_relatorio_impacto":
            out = mcp.call(args.tool, pergunta=args.question)
        elif args.tool == "buscar_impacto_codigo":
            out = mcp.call(args.tool, args.question)
        else:
            out = mcp.call(args.tool, args.question)
        print(out)
    else:
        print("Available tools:", mcp.list_tools())
