"""Export the FastAPI contract used to generate the local panel client."""

import argparse
import json
from pathlib import Path

from alphasense.api import app

path = Path(__file__).resolve().parents[1] / "apps/panel/openapi.json"
schema = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--check", action="store_true")
if parser.parse_args().check:
    if path.read_text(encoding="utf-8") != schema:
        raise SystemExit("Panel OpenAPI contract needs regeneration")
else:
    path.write_text(schema, encoding="utf-8", newline="\n")
