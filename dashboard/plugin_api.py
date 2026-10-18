"""Personal Tasks plugin API: HTTP endpoint for UI and agent communication."""
import json
import base64
import asyncio
from pathlib import Path
from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import JSONResponse

# Import our backend
_backend_path = Path(__file__).resolve().parent.parent / "backend.py"
_spec = None
try:
    import importlib.util
    _spec = importlib.util.spec_from_file_location("personal_tasks_backend", _backend_path)
except Exception:
    pass
if _spec is None or _spec.loader is None:
    raise ImportError("The personal-tasks backend is missing.")
_backend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_backend)

router = APIRouter()

@router.get("/health")
async def health():
    return {"status": "ok"}

async def operation(payload: dict):
    """Dispatch to backend tool handler."""
    # payload shape from jot's frontend: { "kind": "http", "method": "GET/POST", "path": "/rpc", "body": {...}, "headers": {...} }
    # For tool calls via the agent, the body will contain the tool name and args.
    # We'll ignore kind/method/path and treat body as the tool call.
    # If body has a "method" field, treat that as tool name and the rest as args.
    # Otherwise, assume body is the args and tool name is inferred from context? Safer to expect method.
    tool_name = payload.get("method")
    if not tool_name:
        # fallback: assume the whole body is args and tool name is known from UI context? Not safe.
        # Instead, look for a field like "tool" - but we keep simple: require method.
        return JSONResponse({"error": {"code": "MISSING_METHOD", "message": "Tool name required in 'method' field"}}, status_code=400)
    # Remove method from args
    args = {k: v for k, v in payload.items() if k != "method"}
    # Also strip known payload fields that are not args
    for key in ("kind", "path", "body", "headers", "etag"):
        args.pop(key, None)
    # Call backend
    result_json = _backend.handle_call(tool_name, args)
    try:
        result = json.loads(result_json)
    except Exception:
        # If not JSON, wrap
        result = {"raw": result_json}
    return JSONResponse(content=result)

# For compatibility with jot's UI expectations, also provide /editor and /attachments if needed.
# Since we don't have rich text, we can stub them.
@router.get("/editor")
async def editor():
    # Return a simple HTML editor placeholder
    html = """<html><body><h2>Personal Tasks Editor</h2><p>This is a placeholder.</p></body></html>"""
    return {"src": "data:text/html;base64," + base64.b64encode(html.encode()).decode()}

@router.post("/attachments")
async def upload(file: UploadFile = File(...)):
    # We don't support attachments; reject or ignore.
    return JSONResponse({"error": {"code": "NOT_SUPPORTED", "message": "Attachments not supported"}}, status_code=400)
