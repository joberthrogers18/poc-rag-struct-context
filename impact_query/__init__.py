"""Query layer for impact analysis."""

from langchain_core.messages import AIMessage

def _apply_langchain_patches():
    """
    Filtro para remover 'thought_signature' e evitar crash de validação do LangChain.
    """
    _original_init = AIMessage.__init__

    def _patched_init(self, *args, **kwargs):
        if "tool_calls" in kwargs and kwargs["tool_calls"]:
            for tc in kwargs["tool_calls"]:
                if isinstance(tc, dict):
                    tc.pop("thought_signature", None)
                    if "args" in tc and isinstance(tc["args"], dict):
                        tc["args"].pop("thought_signature", None)
        _original_init(self, *args, **kwargs)

    AIMessage.__init__ = _patched_init

# Executa o patch assim que o pacote é inicializado
_apply_langchain_patches()
