"""Personal Tasks backend: SQLite storage for tasks with checklists, priorities, projects."""
import json
import sqlite3
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Storage directory: ~/.hermes/plugin-data/personal-tasks
# Using the documented plugin storage API (if available) else fallback.
def _get_storage_root() -> Path:
    try:
        from plugins.plugin_storage import plugin_data_dir
        return plugin_data_dir("personal-tasks")
    except ImportError:
        # Fallback to ~/.hermes/plugin-data/personal-tasks
        home = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
        return Path(home) / "plugin-data" / "personal-tasks"

STORAGE_ROOT = _get_storage_root()
DB_PATH = STORAGE_ROOT / "tasks.db"

# Ensure storage directory exists
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)

def _get_db() -> sqlite3.Connection:
    """Get a connection to the SQLite DB, creating tables if needed."""
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.execute("PRAGMA foreign_keys = ON")
    # Create tables if not exist
    db.executescript("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        text TEXT,
        project TEXT,
        priority TEXT DEFAULT 'medium' CHECK (priority IN ('low', 'medium', 'high')),
        status TEXT DEFAULT 'todo' CHECK (status IN ('todo', 'in-progress', 'done')),
        revision INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS checklist_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        text TEXT NOT NULL,
        checked INTEGER NOT NULL DEFAULT 0,
        position INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS task_projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        color TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project);
    CREATE INDEX IF NOT EXISTS idx_checklist_task ON checklist_items(task_id);
    """)
    # Update timestamp trigger
    db.execute("""
    CREATE TRIGGER IF NOT EXISTS update_tasks_timestamp
    AFTER UPDATE ON tasks
    BEGIN
        UPDATE tasks SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
    END;
    """)
    return db

def _dict_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}

# --- Tool implementations ---
def pt_list(args: Dict[str, Any]) -> Dict[str, Any]:
    """List tasks with optional filters."""
    db = _get_db()
    where = []
    params = []
    if args.get("project"):
        where.append("project = ?")
        params.append(args["project"])
    if args.get("status"):
        where.append("status = ?")
        params.append(args["status"])
    if args.get("priority"):
        where.append("priority = ?")
        params.append(args["priority"])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    limit = args.get("limit", 20)
    offset = args.get("offset", 0)
    cur = db.execute(f"""
        SELECT id, title, project, priority, status, revision, created_at, updated_at
        FROM tasks
        {where_sql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    """, (*params, limit, offset))
    tasks = [_dict_from_row(r) for r in cur.fetchall()]
    return {"tasks": tasks, "count": len(tasks)}

def pt_read(args: Dict[str, Any]) -> Dict[str, Any]:
    """Read a single task with its checklist items."""
    task_id = args["id"]
    db = _get_db()
    cur = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError("Task not found")
    task = _dict_from_row(row)
    # Load checklist items
    cur = db.execute("""
        SELECT id, text, checked, position
        FROM checklist_items
        WHERE task_id = ?
        ORDER BY position, id
    """, (task_id,))
    task["checklist"] = [_dict_from_row(r) for r in cur.fetchall()]
    # No sub-tasks implemented yet; could add parent_id self-ref if needed
    task["subtasks"] = []
    return task

def pt_create(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new task."""
    db = _get_db()
    cur = db.execute("""
        INSERT INTO tasks (title, text, project, priority, status)
        VALUES (?, ?, ?, ?, ?)
    """, (
        args["title"],
        args.get("text", ""),
        args.get("project"),
        args.get("priority", "medium"),
        args.get("status", "todo")
    ))
    task_id = cur.lastrowid
    db.commit()
    # Return the created task with revision etc.
    return pt_read({"id": str(task_id)})

def pt_update(args: Dict[str, Any]) -> Dict[str, Any]:
    """Update a task; requires matching revision."""
    task_id = args["id"]
    rev = args["revision"]
    db = _get_db()
    # Ensure task exists and revision matches
    cur = db.execute("SELECT revision FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError("Task not found")
    if row[0] != rev:
        raise ValueError("Revision mismatch")
    # Build update fields dynamically
    fields = []
    params = []
    for field in ("title", "text", "project", "priority", "status"):
        if field in args:
            fields.append(f"{field} = ?")
            params.append(args[field])
    if not fields:
        # Nothing to update
        return pt_read({"id": str(task_id)})
    params.extend([rev, task_id])  # for WHERE revision = ? AND id = ?
    db.execute(f"""
        UPDATE tasks
        SET {', '.join(fields)}
        WHERE revision = ? AND id = ?
    """, params)
    if db.total_changes == 0:
        raise ValueError("Update failed: revision mismatch or task deleted")
    db.commit()
    return pt_read({"id": str(task_id)})

def pt_delete(args: Dict[str, Any]) -> Dict[str, Any]:
    """Delete a task; requires matching revision."""
    task_id = args["id"]
    rev = args["revision"]
    db = _get_db()
    cur = db.execute("SELECT revision FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError("Task not found")
    if row[0] != rev:
        raise ValueError("Revision mismatch")
    db.execute("DELETE FROM tasks WHERE id = ? AND revision = ?", (task_id, rev))
    if db.total_changes == 0:
        raise ValueError("Delete failed: revision mismatch")
    db.commit()
    return {"deleted": True, "id": str(task_id)}

def pt_set_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """Check/uncheck a checklist item by index."""
    task_id = args["id"]
    rev = args["revision"]
    idx = args["index"]  # 1-based
    checked = args[["checked"]]
    db = _get_db()
    # Verify task and revision
    cur = db.execute("SELECT revision FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    if not row:
        raise ValueError("Task not found")
    if row[0] != rev:
        raise ValueError("Revision mismatch")
    # Get the checklist item at position idx-1 (we order by position, id)
    cur = db.execute("""
        SELECT id FROM checklist_items
        WHERE task_id = ?
        ORDER BY position, id
        LIMIT 1 OFFSET ?
    """, (task_id, idx - 1))
    row = cur.fetchone()
    if not row:
        raise ValueError("Checklist item not found at index")
    item_id = row[0]
    db.execute("""
        UPDATE checklist_items
        SET checked = ?
        WHERE id = ?
    """, (1 if checked else 0, item_id))
    db.commit()
    return pt_read({"id": str(task_id)})

# --- Dispatcher for handle_call ---
def handle_call(name: str, args: Dict[str, Any]) -> str:
    """Dispatch a tool call to the appropriate function, returning JSON string."""
    try:
        if name == "pt_list":
            res = pt_list(args)
        elif name == "pt_read":
            res = pt_read(args)
        elif name == "pt_create":
            res = pt_create(args)
        elif name == "pt_update":
            res = pt_update(args)
        elif name == "pt_delete":
            res = pt_delete(args)
        elif name == "pt_set_task":
            res = pt_set_task(args)
        else:
            raise ValueError(f"Unknown tool: {name}")
        return json.dumps(res)
    except Exception as e:
        # Return error as JSON; the agent will see it as tool result
        return json.dumps({"error": str(e), "type": e.__class__.__name__})
