"""Authenticated local-only BME operations; no arbitrary file/command endpoints."""
from __future__ import annotations

import base64
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from caelo_core.state import Backend, get_backend
from .engine.safety import SafetyError
from .billing import Balance, read_balance, save_balance

router = APIRouter(prefix="/bme", tags=["bme"])


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=80)
    arguments: dict = Field(default_factory=dict)


@router.get("/status")
def status(b: Backend = Depends(get_backend)):
    return {**b.bme.status(), 'balance': read_balance(), 'openai_configured': b.has_openai_api_key()}


@router.put("/balance")
def balance(value: Balance):
    return save_balance(value)


@router.post("/monitor/stop")
def stop_monitor(b: Backend = Depends(get_backend)):
    with b.bme.lock:
        b.bme.workspace.stop_monitor()
    return {"running": False}


@router.get("/preview/{review_id}")
def preview(review_id: str, b: Backend = Depends(get_backend)):
    from .engine.workflow import render
    with b.bme.lock:
        reviewed = b.bme.workspace.reviews.get(review_id)
        if reviewed is None:
            raise HTTPException(404, "The preview has expired. Review the chart plan again.")
        result = render(reviewed)
    return {"image_uri": "data:image/png;base64," + base64.b64encode(result.chart.png).decode("ascii")}


@router.get("/models")
def models(b: Backend = Depends(get_backend)):
    if not b.has_openai_api_key():
        return {"models": [], "configured": False}
    try:
        ids = b.get_provider("openai").available_model_ids(force=True)
        # Account availability is real; prefix is only a text-model heuristic.
        # /models does NOT establish Responses/tool/vision compatibility.
        candidates = [m for m in ids if m.startswith(("gpt-", "o1", "o3", "o4"))
                      and not any(p in m for p in ("audio", "realtime", "transcribe", "tts", "image", "search"))]
        from caelo_core.models import get_model_registry
        registry_default = get_model_registry().default_for('openai', 'chat')
        preferred = b.read_settings().get('code_model')
        fallback = registry_default.id if registry_default else ''
        selected = preferred if preferred in candidates else fallback if fallback in candidates else ''
        if not selected:
            selected = next((m for m in candidates if m.startswith(('gpt-6', 'gpt-5', 'gpt-4.1', 'gpt-4o', 'o3', 'o4'))), '')
        return {"models": candidates, "configured": True,
                "default_model": selected,
                "note": "Account-returned text-model candidates. Responses/tool compatibility is determined by the actual request."}
    except Exception as exc:
        from .controller import public_error
        raise HTTPException(502, public_error(exc))


@router.post("/tool")
def tool(req: ToolRequest, b: Backend = Depends(get_backend)):
    # This route runs deterministic local operations, never an LLM.
    # save_draft/export_chart are deliberate clicks in the local workflow UI.
    try:
        value = dict(b.bme.call(req.name, req.arguments))
        image = value.pop("_image", None)
        if image is not None:
            value["image_uri"] = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
        return value
    except SafetyError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        raise HTTPException(400, "Analysis failed. Check the file format and data mapping.")


@router.get("/artifacts")
def artifacts(b: Backend = Depends(get_backend)):
    from .engine.safety import checked_root, source_path
    output = b.bme.output
    if not output.exists():
        return {"files": []}
    root = checked_root(output)
    files = []
    for p in sorted(root.iterdir(), key=lambda x: x.name, reverse=True):
        if p.suffix.lower() not in {".png", ".zip", ".svg", ".md", ".txt"}:
            continue
        try:
            source_path(root, p.name)
            files.append({"name": p.name, "bytes": p.stat().st_size})
        except (SafetyError, OSError):
            pass
        if len(files) >= 100:
            break
    return {"files": files}


@router.get("/artifacts/{name}")
def artifact(name: str, b: Backend = Depends(get_backend)):
    try:
        payload = b.bme.artifact(name)
        # JSON via Electron's authenticated request transport; no token-bearing URL.
        mime = "image/png" if name.endswith(".png") else "application/octet-stream"
        return {"name": name, "data_uri": "data:" + mime + ";base64," + base64.b64encode(payload).decode("ascii")}
    except (SafetyError, OSError):
        raise HTTPException(404, "The output file does not exist or cannot be read.")
