"""Personal Tasks: local task storage with checklists, priorities, sub-tasks, projects."""
import json
import sqlite3
from pathlib import Path

from .backend import handle_call


def register(ctx):
    # Load tool schemas from runtime/tools.json
    schemas = json.loads((Path(__file__).parent / "runtime/tools.json").read_text(encoding="utf-8"))
    for schema in schemas:
        name = schema["name"]
        def handler(args, _name=name, **kwargs):
            return handle_call(_name, args)
        ctx.register_tool(name=name, toolset="personal-tasks", schema=schema, handler=handler)
    # Slash command to open the UI
    ctx.register_command(
        "personal-tasks", handle_command,
        description="Open Personal Tasks or manage AI collaboration",
        args_hint="[open|new|capture|ai on|off|status|help]",
    )


def handle_command(args):
    cmd = args.get("command", "").strip().lower()
    if cmd == "open":
        return json.dumps({"opened": True})
    elif cmd == "new":
        # fallback to pt_create via agent_call? For simplicity just return hint
        return json.dumps({"hint": "Use pt_create to add a task"})
    else:
        return json.dumps({"error": "Unknown command"})
