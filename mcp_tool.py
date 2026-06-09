import argparse

from impact_query.service import (
    generate_impact_report_text,
    search_impact_code_json,
)
from mcp_framework import FastMCP


mcp = FastMCP("ImpactAnalyzer")


@mcp.tool()
def buscar_impacto_codigo(pergunta: str) -> str:
    """Busca os artefatos mais parecidos com a pergunta usando a camada impact_query."""
    return search_impact_code_json(pergunta)


@mcp.tool()
def gerar_relatorio_impacto(ids: list = None, pergunta: str = None) -> str:
    """Gera um relatório de impacto consolidado a partir de ids ou de uma pergunta."""
    return generate_impact_report_text(pergunta=pergunta, ids=ids)


def main():
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


if __name__ == "__main__":
    main()
