import asyncio
from contextlib import AsyncExitStack
from typing import Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.types import ListToolsResult, TextContent

from app.logger import logger
from app.tool.base import BaseTool, ToolResult
from app.tool.tool_collection import ToolCollection


class MCPClientTool(BaseTool):
    """Represents a tool proxy that can be called on the MCP server from the client side."""

    session: Optional[ClientSession] = None
    server_id: str = ""  # Add server identifier
    original_name: str = ""

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool by making a remote call to the MCP server."""
        if not self.session:
            return ToolResult(error="Not connected to MCP server")

        try:
            logger.info(f"Executing tool: {self.original_name}")
            result = await self.session.call_tool(self.original_name, kwargs)
            content_str = ", ".join(
                item.text for item in result.content if isinstance(item, TextContent)
            )
            return ToolResult(output=content_str or "No output returned.")
        except Exception as e:
            return ToolResult(error=f"Error executing tool: {str(e)}")


class MCPClients(ToolCollection):
    """
    A collection of tools that connects to multiple MCP servers and manages available tools through the Model Context Protocol.
    """

    sessions: Dict[str, ClientSession] = {}
    _running: Dict[str, bool] = {}
    _task: Dict[str, asyncio.Task] = {}
    description: str = "MCP client tools for server interaction"

    def __init__(self):
        super().__init__()  # Initialize with empty tools list
        self.name = "mcp"  # Keep name for backward compatibility

    async def connect_sse(self, server_url: str, server_id: str = "") -> None:
        """Connect to an MCP server using SSE transport."""
        if not server_url:
            raise ValueError("Server URL is required.")

        server_id = server_id or server_url

        # Always ensure clean disconnection before new connection
        if server_id in self.sessions:
            await self.disconnect(server_id)

        self._running[server_id] = True
        self._task[server_id] = asyncio.create_task(self._sse_session_loop(server_url, server_id))

    async def _sse_session_loop(self, server_url, server_id):
      try:
        logger.info(f"🔄 尝试连接 SSE: {server_url}")
        async with sse_client(url = server_url) as streams:
            logger.info(f"✅ SSE streams 获取成功: {streams}")
            async with ClientSession(*streams) as session:
                logger.info(f"✅ ClientSession 创建成功")
                self.sessions[server_id] = session
                logger.info("🔄 调用 session.initialize()")
                await session.initialize()
                logger.info("✅ initialize 完成")
                await self._initialize_and_list_tools(server_id)
                logger.info("✅ 工具初始化完成")
                while self._running:
                    await asyncio.sleep(0.1)
      except Exception as e:
        logger.error(f"❌ SSE 连接失败: {e}", exc_info=True)
        self.sessions.pop(server_id, None)
      finally:
        logger.info(f"🧹 清理 {server_id}")

    async def connect_stdio(
        self, command: str, args: List[str], server_id: str = ""
    ) -> None:
        """Connect to an MCP server using stdio transport."""
        if not command:
            raise ValueError("Server command is required.")

        server_id = server_id or command

        # Always ensure clean disconnection before new connection
        if server_id in self.sessions:
            await self.disconnect(server_id)

        server_params = StdioServerParameters(command=command, args=args)

        self._running[server_id] = True
        self._task[server_id] = asyncio.create_task(self._stdio_session_loop(server_params, server_id))

    async def _stdio_session_loop(self, server_params, server_id):
        async with stdio_client(server_params) as streams:
            async with ClientSession(*streams) as session:
                self.sessions[server_id] = session
                await session.initialize()
                await self._initialize_and_list_tools(server_id)
                while self._running:
                    await asyncio.sleep(0.1)

    async def _initialize_and_list_tools(self, server_id: str) -> None:
        """Initialize session and populate tool map."""
        session = self.sessions.get(server_id)
        if not session:
            raise RuntimeError(f"Session not initialized for server {server_id}")

        await session.initialize()
        response = await session.list_tools()

        # Create proper tool objects for each server tool
        for tool in response.tools:
            original_name = tool.name
            tool_name = f"mcp_{server_id}_{original_name}"
            tool_name = self._sanitize_tool_name(tool_name)

            server_tool = MCPClientTool(
                name=tool_name,
                description=tool.description,
                parameters=tool.inputSchema,
                session=session,
                server_id=server_id,
                original_name=original_name,
            )
            self.tool_map[tool_name] = server_tool

        # Update tools tuple
        self.tools = tuple(self.tool_map.values())
        logger.info(
            f"Connected to server {server_id} with tools: {[tool.name for tool in response.tools]}"
        )

    def _sanitize_tool_name(self, name: str) -> str:
        """Sanitize tool name to match MCPClientTool requirements."""
        import re

        # Replace invalid characters with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)

        # Remove consecutive underscores
        sanitized = re.sub(r"_+", "_", sanitized)

        # Remove leading/trailing underscores
        sanitized = sanitized.strip("_")

        # Truncate to 64 characters if needed
        if len(sanitized) > 64:
            sanitized = sanitized[:64]

        return sanitized

    async def list_tools(self) -> ListToolsResult:
        """List all available tools."""
        tools_result = ListToolsResult(tools=[])
        for session in self.sessions.values():
            response = await session.list_tools()
            tools_result.tools += response.tools
        return tools_result

    async def disconnect(self, server_id: str = "") -> None:
        """Disconnect from a specific MCP server or all servers if no server_id provided."""
        if server_id:
            if server_id in self.sessions:
                try:
                    self._running[server_id] = False
                    self._task[server_id].cancel()
                    await self._task[server_id]

                    # Clean up references
                    self.sessions.pop(server_id, None)
                    self._running.pop(server_id, None)
                    self._task.pop(server_id, None)

                    # Remove tools associated with this server
                    self.tool_map = {
                        k: v
                        for k, v in self.tool_map.items()
                        if v.server_id != server_id
                    }
                    self.tools = tuple(self.tool_map.values())
                    logger.info(f"Disconnected from MCP server {server_id}")
                except Exception as e:
                    logger.error(f"Error disconnecting from server {server_id}: {e}")
        else:
            # Disconnect from all servers in a deterministic order
            for sid in sorted(list(self.sessions.keys())):
                await self.disconnect(sid)
            self.tool_map = {}
            self.tools = tuple()
            logger.info("Disconnected from all MCP servers")
