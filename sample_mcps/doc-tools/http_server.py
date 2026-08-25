"""Serve DocTools over Streamable HTTP.

stdio is not reachable across a container boundary, so the containerized server
uses Streamable HTTP and binds 0.0.0.0 so the mapped port works.
"""

import os

from doc_tools_server import mcp

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # In SDK v2, transport and networking options live on run(), not on the
    # MCPServer constructor.
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)
