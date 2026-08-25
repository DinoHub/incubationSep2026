"""Container healthcheck for an authenticated server.

The Protected Resource Metadata document is the one endpoint that must answer
without a token — it is how a client discovers where to get one. That makes it a
better liveness check than a bare TCP connect: it proves the app is serving and
that the auth layer is configured, not just that something bound the port.

Stdlib only, so it adds nothing to the image.
"""

import os
import sys
import urllib.request

port = os.environ.get("PORT", "8001")
url = f"http://127.0.0.1:{port}/.well-known/oauth-protected-resource"
try:
    with urllib.request.urlopen(url, timeout=3) as r:
        sys.exit(0 if r.status == 200 else 1)
except OSError:
    sys.exit(1)
