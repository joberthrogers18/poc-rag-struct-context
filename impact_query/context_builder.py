import inspect


# --- Funções Auxiliares de Validação e Formatação ---

def _is_etl_file(path: str | None) -> bool:
    """Verifica se o caminho do arquivo indica que ele faz parte de um ETL."""
    if not path:
        return False
    etl_keywords = ["etl", "pipeline", "jobs", "airflow", "dag", "dbt"]
    return any(keyword in path.lower() for keyword in etl_keywords)


def format_list(items: list[str], empty_message: str) -> str:
    """Uniformiza como listas aparecem no fallback textual."""
    return ", ".join(items) if items else empty_message


def estimate_risk(files_count: int, columns_count: int, etl_count: int) -> str:
    """Heurística simples para dar um nível de risco antes do texto final do LLM."""
    if files_count >= 5 or etl_count > 0:
        return "alto"
    if files_count >= 3 or columns_count >= 2:
        return "medio"
    return "baixo"


def _generate_suggested_actions(columns: set[str], etl_files: set[str], total_files: int) -> list[str]:
    """Gera as ações sugeridas com base no impacto encontrado."""
    actions = []
    for col in sorted(columns):
        actions.append(
            f"Revisar uso da coluna '{col}' em {total_files} arquivos; avaliar impacto antes de remover."
        )
    if etl_files:
        files_str = ", ".join(sorted(etl_files))
        actions.append(f"Arquivos/ETLs detectados: {files_str}. Verificar jobs de ingestão/transformação.")
    return actions


# --- Funções Principais do Fluxo ---

def build_report(artifacts: list[dict]) -> dict:
    """Consolida sinais dos artefatos encontrados em um mapa de impacto estruturado."""
    
    # Extração de conjuntos únicos (Garante unicidade e remove None/vazios)
    teams = {art["team"] for art in artifacts if art.get("team")}
    files = {art["path"] for art in artifacts if art.get("path")}
    
    tables = {table for art in artifacts for table in art.get("tables_ref") or []}
    columns = {col for art in artifacts for col in art.get("columns_ref") or []}
    
    etl_files = {path for path in files if _is_etl_file(path)}
    
    summaries = [
        {
            "id": art.get("id"),
            "path": art.get("path"),
            "summary": art.get("summary"),
        }
        for art in artifacts
    ]

    return {
        "teams_affected": sorted(teams),
        "tables_affected": sorted(tables),
        "columns_affected": sorted(columns),
        "files_affected": sorted(files),
        "etl_candidates": sorted(etl_files),
        "artifact_summaries": summaries,
        "suggested_actions": _generate_suggested_actions(columns, etl_files, len(files)),
    }


def build_llm_context(report: dict, pergunta: str, artifacts: list[dict]) -> dict:
    """Monta o payload rico que será enviado ao LLM para redigir a resposta final."""
    files_count = len(report["files_affected"])
    columns_count = len(report["columns_affected"])
    etl_count = len(report["etl_candidates"])
    risk = estimate_risk(files_count, columns_count, etl_count)

    key_artifacts = [
        {
            "id": art.get("id"),
            "path": art.get("path"),
            "block_name": art.get("block_name"),
            "block_type": art.get("block_type"),
            "summary": art.get("summary"),
            "tables_ref": art.get("tables_ref") or [],
            "columns_ref": art.get("columns_ref") or [],
            "content_excerpt": (art.get("content") or "")[:1200],
        }
        for art in artifacts[:5]
    ]

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


def build_local_report(report: dict, pergunta: str = None) -> str:
    """Gera uma resposta local quando o LLM estiver indisponível ou sem configuração."""
    lines = ["Relatorio de impacto"]
    if pergunta:
        lines.append(f"Solicitacao analisada: {pergunta}")

    # Cenário sem artefatos relevantes
    if not report["artifact_summaries"]:
        empty_state_msg = inspect.cleandoc("""
            
            Resumo executivo:
            Nao encontrei artefatos relevantes para responder com confianca. Isso normalmente indica que a base ainda nao foi ingerida por completo ou que a pergunta esta generica demais.
            
            Proximos passos:
            1. Rode o ingest.py novamente para atualizar a base vetorial.
            2. Confirme se a tabela artifact_chunks recebeu registros.
            3. Refaca a pergunta incluindo nome da tabela, coluna ou arquivo.
        """)
        lines.append(empty_state_msg)
        return "\n".join(lines)

    # Métricas para cálculo do risco
    files_count = len(report["files_affected"])
    columns_count = len(report["columns_affected"])
    etl_count = len(report["etl_candidates"])
    risk = estimate_risk(files_count, columns_count, etl_count)

    # Construção do Resumo Executivo
    lines.append("\nResumo executivo:")
    lines.append(
        f"A solicitacao parece ter risco {risk}, considerando {files_count} arquivo(s) relacionado(s), "
        f"{columns_count} coluna(s) mencionada(s) e {etl_count} possivel(is) integracao(oes) dependente(s)."
    )
    
    if report["columns_affected"]:
        cols_formatted = format_list(report["columns_affected"], "nenhuma coluna identificada")
        lines.append(f"Os principais pontos de atencao estao nas colunas: {cols_formatted}.")
    else:
        lines.append("Nao houve correspondencia direta de colunas, entao a validacao manual dos arquivos retornados continua importante.")

    # Mapeamento de Impacto
    lines.extend([
        "\nImpacto identificado:",
        f"Times afetados: {format_list(report['teams_affected'], 'nenhum time identificado')}",
        f"Arquivos afetados: {format_list(report['files_affected'], 'nenhum arquivo identificado')}",
        f"Tabelas afetadas: {format_list(report['tables_affected'], 'nenhuma tabela identificada')}",
        f"Colunas afetadas: {format_list(report['columns_affected'], 'nenhuma coluna identificada')}"
    ])
    
    if report["etl_candidates"]:
        lines.append(f"Possiveis ETLs ou jobs afetados: {format_list(report['etl_candidates'], 'nenhum fluxo identificado')}")

    # Artefatos Relevantes
    lines.append("\nArtefatos mais relevantes:")
    for summary in report["artifact_summaries"][:5]:
        id_ = summary.get("id")
        path = summary.get("path")
        text = summary.get("summary") or "Sem resumo disponivel."
        lines.append(f"- [{id_}] {path}: {text}")

    # Próximos Passos Recomendados
    lines.extend([
        "\nComo eu seguiria:",
        "1. Validaria onde esse campo aparece no schema, repositorio e camada de servico.",
        "2. Conferiria leituras, escritas, filtros, ordenacoes e serializacao antes de remover."
    ])
    
    step_number = "3" if report["etl_candidates"] else "3"
    if report["etl_candidates"]:
        lines.append("3. Revisaria os jobs ou pipelines detectados para evitar quebra em carga ou transformacao.")
        step_number = "4"

    lines.append(f"{step_number}. So depois removeria a coluna do banco e ajustaria migracoes, testes e contratos.")

    # Checagens sugeridas adicionais
    if report["suggested_actions"]:
        lines.append("\nChecagens sugeridas:")
        lines.extend(f"- {action}" for action in report["suggested_actions"])

    return "\n".join(lines)