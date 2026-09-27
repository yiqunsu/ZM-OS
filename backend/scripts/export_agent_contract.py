"""Export SSE event names without importing application settings or a database."""

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend/app/models/agent.py"
TARGET = ROOT / "frontend/components/agent/contracts.generated.ts"


def render() -> str:
    tree = ast.parse(SOURCE.read_text())
    assignment = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "EVENT_KINDS" for target in node.targets)
    )
    events = ast.literal_eval(assignment.value)
    if not events or not all(isinstance(event, str) for event in events) or len(set(events)) != len(events):
        raise ValueError("EVENT_KINDS must contain unique event names")
    values = "\n".join(f"  {json.dumps(event)}," for event in events)
    return (
        "// Generated from backend/app/models/agent.py; do not edit.\n"
        "// Regenerate: python3 backend/scripts/export_agent_contract.py\n\n"
        f"export const EVENT_KINDS = [\n{values}\n] as const;\n\n"
        "export type EventKind = (typeof EVENT_KINDS)[number];\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed contract is stale")
    args = parser.parse_args()
    expected = render()
    if args.check:
        if not TARGET.exists() or TARGET.read_text() != expected:
            parser.exit(1, "Agent contract is stale; run python3 backend/scripts/export_agent_contract.py\n")
    else:
        TARGET.write_text(expected)


if __name__ == "__main__":
    main()
