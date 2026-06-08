from typing import Callable, Dict, Any


class FastMCP:
    """Minimal MCP-like registry for local tools.

    Usage:
        mcp = FastMCP("Name")

        @mcp.tool()
        def my_tool(arg: str) -> str:
            return "..."

        mcp.call("my_tool", "arg")
    """

    def __init__(self, name: str):
        self.name = name
        self._tools: Dict[str, Callable[..., Any]] = {}

    def tool(self, name: str = None):
        def decorator(func: Callable[..., Any]):
            tool_name = name or func.__name__
            self._tools[tool_name] = func
            return func

        return decorator

    def call(self, tool_name: str, *args, **kwargs) -> Any:
        if tool_name not in self._tools:
            raise ValueError(f"Tool '{tool_name}' not found")
        return self._tools[tool_name](*args, **kwargs)

    def list_tools(self):
        return list(self._tools.keys())
