"""Put starting documents in the working directory so the tools have something
to act on.

Run it in a throwaway container; the volume mount means the files land in
./documents on your host:

    docker compose run --rm mcp-server python seed_data.py
"""

import os
from pathlib import Path

WORK_DIR = Path(os.environ.get("DOCUMENTS_DIR", "documents")).resolve()
WORK_DIR.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "meeting-notes.txt": (
        "Team sync, 12 August\n"
        "Attending: Ana, Bo, Chen\n"
        "\n"
        "Decision: ship the importer behind a flag.\n"
        "Open question: who owns the migration rollback?\n"
        "Action: Bo to draft the rollback plan by Friday.\n"
    ),
    "roadmap.txt": (
        "Q3 roadmap\n"
        "\n"
        "1. Importer, behind a flag.\n"
        "2. Migration tooling, including rollback.\n"
        "3. Search over archived documents.\n"
    ),
}

for name, text in SAMPLES.items():
    out = WORK_DIR / name
    out.write_text(text, encoding="utf-8")
    print(f"Created {out} ({out.stat().st_size} bytes)")
