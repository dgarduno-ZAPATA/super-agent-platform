from __future__ import annotations

import csv
import io
import json
import os
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from openai import AsyncOpenAI

from adapters.storage.repositories.audit_log_repo import PostgresAuditLogRepository
from api.dependencies import (
    get_audit_log_repository,
    get_current_user,
    get_llm_provider,
)
from core.domain.messaging import ChatMessage
from core.ports.llm_provider import LLMProvider

router = APIRouter(tags=["admin"])

_CHUNK_SIZE = 20
_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "name": ("elemento", "nombre", "name", "contacto"),
    "vehicle": ("vehiculo", "vehicle", "modelo"),
    "summary": ("resumen", "summary", "nota"),
    "template": ("template",),
}


def _normalize_column(value: str) -> str:
    return value.strip().lower().replace("_", " ").replace("-", " ")


def _detect_column(headers: Sequence[str], aliases: Sequence[str]) -> str | None:
    normalized_aliases = {_normalize_column(alias) for alias in aliases}
    for header in headers:
        if _normalize_column(header) in normalized_aliases:
            return header
    return None


def _extract_json_array(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass

    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("LLM did not return a valid JSON array")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("LLM output is not a JSON array")
    return [item for item in parsed if isinstance(item, dict)]


async def _complete_with_openai(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured for fallback")

    model = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini")
    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=4000,
    )
    text = response.choices[0].message.content
    if not isinstance(text, str):
        raise RuntimeError("Invalid OpenAI response")
    return text.strip()


@router.post("/admin/generate-templates", response_model=None)
async def generate_templates_csv(
    file: Annotated[UploadFile, File(...)],
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    llm_provider: Annotated[LLMProvider, Depends(get_llm_provider)],
) -> StreamingResponse | JSONResponse:
    del current_user
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Archivo inválido. Debe ser CSV."},
        )

    try:
        raw = await file.read()
        text = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        if not headers:
            raise ValueError("CSV sin encabezados")
        rows = list(reader)
        if not rows:
            raise ValueError("CSV sin filas")

        name_col = _detect_column(headers, _COLUMN_SYNONYMS["name"])
        vehicle_col = _detect_column(headers, _COLUMN_SYNONYMS["vehicle"])
        summary_col = _detect_column(headers, _COLUMN_SYNONYMS["summary"])
        template_col = _detect_column(headers, _COLUMN_SYNONYMS["template"]) or "Template"

        if not name_col or not vehicle_col or not summary_col:
            raise ValueError("No se detectaron columnas mínimas: nombre, vehiculo, resumen")

        if template_col not in headers:
            headers = [*headers, template_col]
            for row in rows:
                row[template_col] = ""

        for start in range(0, len(rows), _CHUNK_SIZE):
            chunk = rows[start : start + _CHUNK_SIZE]
            prospects: list[dict[str, object]] = []
            for idx, row in enumerate(chunk):
                prospects.append(
                    {
                        "id": idx,
                        "nombre": (row.get(name_col) or "").strip(),
                        "vehiculo": (row.get(vehicle_col) or "").strip(),
                        "resumen": (row.get(summary_col) or "").strip(),
                    }
                )

            prompt = (
                "Eres Raúl Rodríguez, ejecutivo de ventas de camiones seminuevos.\n"
                "Genera un template de WhatsApp de seguimiento para cada prospecto.\n\n"
                "REGLAS:\n"
                "1. Máximo 2 oraciones cortas\n"
                "2. Usa spintax: [opción1|opción2|opción3]\n"
                "3. Referencia ESPECÍFICA al vehículo o resumen del prospecto\n"
                "4. Tono: profesional y cálido, NO coloquial\n"
                "5. NO incluyas saludo con nombre (se agrega automáticamente)\n"
                "6. NO incluyas nombre del bot ni empresa (se agrega automáticamente)\n"
                "7. Empieza directo con el follow-up\n"
                "8. Usa {vehiculo} para el vehículo de interés\n\n"
                f"PROSPECTOS:\n{json.dumps(prospects, ensure_ascii=False)}\n\n"
                "Responde ÚNICAMENTE con JSON array (sin markdown):\n"
                '[{"id": 0, "template": "..."}, ...]'
            )

            try:
                llm_response = await llm_provider.complete(
                    messages=[ChatMessage(role="user", content=prompt)],
                    system="Responde solo JSON válido.",
                    tools=None,
                    temperature=0.2,
                )
                llm_text = llm_response.content
            except Exception:
                llm_text = await _complete_with_openai(prompt)

            parsed = _extract_json_array(llm_text)
            template_by_idx: dict[int, str] = {}
            for item in parsed:
                idx = item.get("id")
                template = item.get("template")
                if isinstance(idx, int) and isinstance(template, str):
                    template_by_idx[idx] = template.strip()

            for idx, row in enumerate(chunk):
                row[template_col] = template_by_idx.get(idx, row.get(template_col, "")).strip()

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        output.seek(0)
        filename = f"templates_raul_{len(rows)}_contactos.csv"
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": str(exc)},
        )


@router.get("/admin/audit-log")
async def get_audit_log(
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    audit_log_repo: Annotated[PostgresAuditLogRepository, Depends(get_audit_log_repository)],
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
) -> dict[str, object]:
    del current_user
    entries = await audit_log_repo.list(limit=limit, offset=offset, action=action)
    return {"entries": entries, "limit": max(1, min(limit, 200)), "offset": max(0, offset)}


@router.get("/admin", response_class=HTMLResponse)
async def admin_panel() -> HTMLResponse:
    html = r"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Panel Admin</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Outfit:wght@300;400;500;600;700&display=swap');
    :root {
      --brand-primary: #1a5276;
      --brand-accent: #2e86c1;
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --accent: var(--brand-accent);
      --text: #e2e8f0;
      --muted: #94a3b8;
      --danger: #ef4444;
      --warn: #f59e0b;
      --success: #22c55e;
      --info: #38bdf8;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    .hidden { display: none !important; }
    .center-wrap {
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 20px;
    }
    .card {
      width: 100%;
      max-width: 420px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 24px;
      box-shadow: 0 10px 30px rgba(2, 6, 23, 0.45);
    }
    .title {
      margin: 0 0 6px;
      font-size: 1.2rem;
      font-weight: 700;
    }
    .subtitle {
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 0.92rem;
    }
    label {
      display: block;
      margin-bottom: 6px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    input {
      width: 100%;
      background: #0b1220;
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 10px 12px;
      outline: none;
      margin-bottom: 14px;
    }
    input:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(34, 211, 238, 0.2);
    }
    button {
      border: 1px solid transparent;
      border-radius: 10px;
      padding: 10px 14px;
      font-weight: 600;
      cursor: pointer;
    }
    .btn-primary {
      width: 100%;
      background: var(--accent);
      color: #06222a;
    }
    .error {
      color: var(--danger);
      margin-top: 8px;
      min-height: 20px;
      font-size: 0.9rem;
    }
    .panel {
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    .navbar {
      background: var(--card);
      border-bottom: 1px solid var(--border);
      padding: 14px 20px 0;
    }
    .navbar h1 {
      margin: 0 0 12px;
      font-size: 1.05rem;
      font-weight: 700;
    }
    .tabs {
      display: flex;
      gap: 18px;
      overflow-x: auto;
      padding-bottom: 0;
    }
    .tab {
      appearance: none;
      background: transparent;
      border: 0;
      border-bottom: 2px solid transparent;
      color: var(--muted);
      border-radius: 0;
      padding: 8px 0 10px;
      white-space: nowrap;
    }
    .tab.active {
      color: var(--text);
      border-bottom-color: var(--accent);
    }
    .content {
      padding: 20px;
      flex: 1;
    }
    .placeholder {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
      color: var(--muted);
    }
    .toast-wrap {
      position: fixed;
      top: 16px;
      right: 16px;
      z-index: 1000;
      display: grid;
      gap: 10px;
      width: min(340px, calc(100vw - 32px));
    }
    .toast {
      background: #0b1220;
      border: 1px solid var(--border);
      border-left: 4px solid var(--info);
      border-radius: 10px;
      padding: 12px;
      box-shadow: 0 8px 24px rgba(2, 6, 23, 0.4);
      font-size: 0.92rem;
    }
    .toast.success { border-left-color: var(--success); }
    .toast.error { border-left-color: var(--danger); }
    .toast.info { border-left-color: var(--info); }
    .dashboard {
      display: grid;
      gap: 16px;
    }
    .dashboard-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 24px;
    }
    .section-heading .spinner { margin: 0; }
    .spinner {
      width: 16px;
      height: 16px;
      border: 2px solid var(--border);
      border-top-color: var(--accent);
      border-radius: 999px;
      animation: spin 0.8s linear infinite;
    }
    .dash-error {
      color: #fecaca;
      background: rgba(239, 68, 68, 0.08);
      border: 1px solid rgba(239, 68, 68, 0.35);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 0.9rem;
    }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    @media (min-width: 900px) {
      .metric-grid {
        grid-template-columns: repeat(4, minmax(0, 1fr));
      }
    }
    @media (max-width: 720px) {
      .metric-grid {
        grid-template-columns: 1fr;
      }
    }
    .metric-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
    }
    .metric-card.dlq-alert {
      border-color: var(--danger);
      box-shadow: inset 0 0 0 1px rgba(239, 68, 68, 0.3);
    }
    .metric-label {
      color: var(--muted);
      font-size: 0.86rem;
      margin-bottom: 6px;
    }
    .metric-value {
      font-size: 1.35rem;
      font-weight: 700;
    }
    .health {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: flex;
      gap: 10px;
      align-items: flex-start;
    }
    .health-dot {
      width: 12px;
      height: 12px;
      border-radius: 999px;
      margin-top: 4px;
      flex: 0 0 auto;
    }
    .health-dot.green { background: var(--success); }
    .health-dot.yellow { background: var(--warn); }
    .health-dot.red { background: var(--danger); }
    .fsm-wrap {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
    }
    .fsm-title {
      margin: 0 0 10px;
      font-size: 0.95rem;
      color: var(--text);
    }
    .fsm-item {
      margin-bottom: 10px;
    }
    .fsm-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.85rem;
      color: var(--muted);
      margin-bottom: 5px;
      gap: 8px;
    }
    .fsm-bar-bg {
      background: #0b1220;
      border: 1px solid var(--border);
      border-radius: 8px;
      height: 10px;
      overflow: hidden;
    }
    .fsm-bar-fill {
      height: 100%;
      border-radius: 8px;
      background: linear-gradient(90deg, #22d3ee, #06b6d4);
    }
    .generated-at {
      text-align: right;
      color: var(--muted);
      font-size: 0.75rem;
      margin-top: 6px;
    }
    .campaigns {
      display: grid;
      gap: 14px;
    }
    .campaigns-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      min-height: 24px;
      margin-bottom: 0;
    }
    .mini-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
    @media (max-width: 900px) {
      .mini-grid {
        grid-template-columns: 1fr;
      }
    }
    .mini-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 10px 12px;
    }
    .mini-label {
      color: var(--muted);
      font-size: 0.82rem;
      margin-bottom: 4px;
    }
    .mini-value {
      font-size: 1.2rem;
      font-weight: 700;
    }
    .campaign-run {
      display: grid;
      gap: 10px;
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
    }
    .campaign-run-btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      width: fit-content;
      background: var(--accent);
      color: #06222a;
      border: 0;
    }
    .campaign-result {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 0.92rem;
    }
    .campaign-result.success {
      background: rgba(34, 197, 94, 0.12);
      border-color: rgba(34, 197, 94, 0.45);
      color: #bbf7d0;
    }
    .campaign-result.error {
      background: rgba(239, 68, 68, 0.08);
      border-color: rgba(239, 68, 68, 0.45);
      color: #fecaca;
    }
    .progress-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .goal-row {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    .goal-row input[type="range"] {
      flex: 1 1 220px;
      margin: 0;
    }
    .goal-row input[type="number"] {
      width: 110px;
      margin: 0;
    }
    .progress-track {
      width: 100%;
      height: 12px;
      border-radius: 999px;
      background: #0b1220;
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      border-radius: 999px;
      transition: width 0.2s ease;
    }
    .progress-fill.green { background: #22c55e; }
    .progress-fill.yellow { background: #f59e0b; }
    .progress-fill.cyan { background: #22d3ee; }
    .speed-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .speed-buttons {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .speed-btn {
      background: #0b1220;
      border: 1px solid var(--border);
      color: var(--text);
    }
    .speed-btn.active {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px rgba(34, 211, 238, 0.4);
      color: var(--accent);
    }
    .speed-current {
      font-size: 0.9rem;
      color: var(--muted);
    }
    .activity-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .activity-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .activity-clear {
      background: #0b1220;
      border: 1px solid var(--border);
      color: var(--muted);
    }
    .activity-log {
      margin: 0;
      padding: 0;
      list-style: none;
      max-height: 200px;
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 10px;
      background: #0b1220;
    }
    .activity-item {
      padding: 8px 10px;
      border-bottom: 1px solid rgba(51, 65, 85, 0.5);
      font-size: 0.86rem;
      color: var(--text);
      word-break: break-word;
    }
    .activity-item:last-child {
      border-bottom: 0;
    }
    .activity-empty {
      padding: 10px;
      color: var(--muted);
      font-size: 0.86rem;
    }
    .templates {
      display: grid;
      gap: 14px;
    }
    .templates-layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }
    @media (max-width: 960px) {
      .templates-layout {
        grid-template-columns: 1fr;
      }
    }
    .template-panel {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .template-row {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    @media (max-width: 640px) {
      .template-row {
        grid-template-columns: 1fr;
      }
    }
    .template-select, .template-input, .template-textarea {
      width: 100%;
      background: #0b1220;
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 10px 12px;
      outline: none;
      font-family: inherit;
    }
    .template-textarea {
      min-height: 140px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      line-height: 1.4;
    }
    .chips-wrap {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .chip {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 5px 10px;
      background: #0b1220;
      color: var(--text);
      font-size: 0.82rem;
      cursor: pointer;
    }
    .snippet-grid {
      display: grid;
      gap: 10px;
    }
    .snippet-group {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px;
      background: #0b1220;
    }
    .snippet-title {
      color: var(--muted);
      font-size: 0.82rem;
      margin-bottom: 6px;
    }
    .snippet-item {
      display: block;
      width: 100%;
      text-align: left;
      border: 1px dashed var(--border);
      margin-bottom: 6px;
      background: transparent;
      color: var(--text);
      border-radius: 8px;
      padding: 6px 8px;
      font-size: 0.82rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      cursor: pointer;
    }
    .snippet-item:last-child {
      margin-bottom: 0;
    }
    .template-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .template-btn {
      background: #0b1220;
      border: 1px solid var(--border);
      color: var(--text);
    }
    .template-btn.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #06222a;
    }
    .quality-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .quality-head {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .quality-dot {
      width: 12px;
      height: 12px;
      border-radius: 999px;
      flex: 0 0 auto;
    }
    .quality-dot.green { background: var(--success); }
    .quality-dot.yellow { background: var(--warn); }
    .quality-dot.red { background: var(--danger); }
    .checks-list {
      margin: 0;
      padding-left: 18px;
      color: var(--muted);
      font-size: 0.84rem;
      display: grid;
      gap: 4px;
    }
    .stats-bar {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px;
    }
    @media (max-width: 640px) {
      .stats-bar {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    .stat-chip {
      background: #0b1220;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px;
    }
    .stat-chip-label {
      color: var(--muted);
      font-size: 0.75rem;
      margin-bottom: 2px;
    }
    .stat-chip-value {
      font-size: 1rem;
      font-weight: 700;
    }
    .inject-banner {
      border: 1px solid rgba(168, 85, 247, 0.55);
      background: rgba(168, 85, 247, 0.14);
      color: #e9d5ff;
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 0.85rem;
    }
    .bubble-list {
      display: grid;
      gap: 8px;
    }
    .wa-bubble {
      position: relative;
      background: #005c4b;
      border: 1px solid rgba(255, 255, 255, 0.09);
      border-radius: 10px;
      padding: 18px 12px 18px;
      max-width: 95%;
    }
    .wa-variant {
      position: absolute;
      top: 4px;
      left: 8px;
      color: #cbd5e1;
      font-size: 0.72rem;
    }
    .wa-message {
      white-space: pre-wrap;
      font-size: 0.92rem;
      line-height: 1.35;
    }
    .wa-injected {
      color: #fde047;
    }
    .wa-time {
      position: absolute;
      bottom: 4px;
      right: 8px;
      color: #cbd5e1;
      font-size: 0.7rem;
    }
    .examples-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    @media (max-width: 640px) {
      .examples-grid {
        grid-template-columns: 1fr;
      }
    }
    .example-card {
      border-radius: 10px;
      padding: 10px;
      font-size: 0.82rem;
      line-height: 1.35;
      border: 1px solid transparent;
    }
    .example-card.good {
      border-color: rgba(34, 197, 94, 0.4);
      background: rgba(34, 197, 94, 0.12);
      color: #bbf7d0;
    }
    .example-card.bad {
      border-color: rgba(239, 68, 68, 0.45);
      background: rgba(239, 68, 68, 0.1);
      color: #fecaca;
    }
    .conversations {
      display: grid;
      gap: 14px;
    }
    .conv-search-card,
    .conv-summary-card,
    .conv-events-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
    }
    .conv-search-row {
      display: flex;
      gap: 8px;
      align-items: flex-end;
      flex-wrap: wrap;
    }
    .conv-search-row > div {
      flex: 1 1 360px;
    }
    .conv-search-input {
      width: 100%;
      background: #0b1220;
      border: 1px solid var(--border);
      color: var(--text);
      border-radius: 10px;
      padding: 10px 12px;
      outline: none;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    .conv-search-btn {
      background: var(--accent);
      color: #06222a;
      border: 0;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .conv-search-msg {
      margin-top: 8px;
      font-size: 0.9rem;
      color: var(--muted);
    }
    .conv-search-msg.error {
      color: #fecaca;
    }
    .conv-header-row {
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 10px;
    }
    @media (max-width: 980px) {
      .conv-header-row {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    .conv-header-item {
      background: #0b1220;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
      font-size: 0.84rem;
      color: var(--muted);
    }
    .conv-header-value {
      color: var(--text);
      margin-top: 4px;
      font-size: 0.92rem;
      word-break: break-word;
    }
    .fsm-badge,
    .control-badge {
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      border: 1px solid transparent;
      font-size: 0.8rem;
      font-weight: 600;
      width: fit-content;
    }
    .fsm-idle { background: #374151; border-color: #6b7280; color: #e5e7eb; }
    .fsm-greeting { background: #1d4ed8; border-color: #60a5fa; color: #dbeafe; }
    .fsm-qualification { background: #0e7490; border-color: #22d3ee; color: #cffafe; }
    .fsm-handoff_pending { background: #a16207; border-color: #facc15; color: #fef9c3; }
    .fsm-handoff_active { background: #c2410c; border-color: #fb923c; color: #ffedd5; }
    .fsm-closed { background: #14532d; border-color: #22c55e; color: #dcfce7; }
    .fsm-default { background: #374151; border-color: #6b7280; color: #e5e7eb; }
    .control-bot { background: #14532d; border-color: #22c55e; color: #dcfce7; }
    .control-agent { background: #854d0e; border-color: #f59e0b; color: #fef3c7; }
    .conv-stats-grid {
      display: grid;
      gap: 8px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      margin-bottom: 10px;
    }
    @media (max-width: 840px) {
      .conv-stats-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    .conv-mini-stat {
      background: #0b1220;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px 10px;
    }
    .conv-mini-label {
      color: var(--muted);
      font-size: 0.76rem;
    }
    .conv-mini-value {
      margin-top: 3px;
      font-size: 1rem;
      font-weight: 700;
    }
    .conv-control-row {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .conv-control-btn {
      border: 0;
      display: inline-flex;
      gap: 8px;
      align-items: center;
    }
    .conv-control-btn.take {
      background: #f59e0b;
      color: #1f2937;
    }
    .conv-control-btn.release {
      background: #22c55e;
      color: #052e16;
    }
    .conv-events-scroll {
      max-height: 500px;
      overflow: auto;
      padding: 8px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0b1220;
      display: grid;
      gap: 8px;
    }
    .conv-empty {
      color: var(--muted);
      font-size: 0.9rem;
      padding: 8px 2px;
    }
    .conv-row {
      display: flex;
    }
    .conv-row.inbound { justify-content: flex-start; }
    .conv-row.outbound { justify-content: flex-end; }
    .conv-msg {
      position: relative;
      max-width: 85%;
      border-radius: 12px;
      padding: 10px 10px 18px;
      border: 1px solid var(--border);
      white-space: pre-wrap;
      word-break: break-word;
      font-size: 0.9rem;
      line-height: 1.35;
    }
    .conv-msg.inbound {
      background: #1e293b;
      color: #e2e8f0;
    }
    .conv-msg.outbound {
      background: #005c4b;
      color: #ecfeff;
      border-color: rgba(255, 255, 255, 0.12);
    }
    .conv-time {
      position: absolute;
      right: 8px;
      bottom: 4px;
      color: #cbd5e1;
      font-size: 0.7rem;
    }
    .conv-center-badge {
      justify-self: center;
      background: #1f2937;
      color: #d1d5db;
      border: 1px solid #4b5563;
      border-radius: 999px;
      padding: 5px 10px;
      font-size: 0.75rem;
    }
    .conv-center-badge.handoff {
      background: #78350f;
      color: #fef3c7;
      border-color: #f59e0b;
    }
    .csvgen {
      display: grid;
      gap: 14px;
    }
    .csvgen-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .csvgen-drop {
      border: 1px dashed var(--accent);
      border-radius: 12px;
      padding: 18px;
      text-align: center;
      color: var(--muted);
      background: rgba(34, 211, 238, 0.06);
      cursor: pointer;
    }
    .csvgen-drop.dragover {
      border-color: #67e8f9;
      background: rgba(34, 211, 238, 0.12);
    }
    .csvgen-fileinfo {
      color: var(--text);
      font-size: 0.9rem;
    }
    .csvgen-table-wrap {
      overflow: auto;
      border: 1px solid var(--border);
      border-radius: 10px;
    }
    .csvgen-table {
      width: 100%;
      border-collapse: collapse;
      min-width: 500px;
    }
    .csvgen-table th,
    .csvgen-table td {
      border-bottom: 1px solid rgba(51, 65, 85, 0.6);
      padding: 8px 10px;
      font-size: 0.82rem;
      text-align: left;
      color: var(--text);
      background: #0b1220;
      max-width: 280px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .csvgen-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .csvgen-chip {
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 4px 10px;
      background: #0b1220;
      color: var(--text);
      font-size: 0.8rem;
    }
    .csvgen-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }
    .csvgen-btn {
      background: #0b1220;
      color: var(--text);
      border: 1px solid var(--border);
    }
    .csvgen-btn.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #06222a;
    }
    .csvgen-result-error {
      border: 1px solid rgba(239, 68, 68, 0.5);
      background: rgba(239, 68, 68, 0.1);
      color: #fecaca;
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 0.9rem;
    }
    .csvgen-preview-list {
      display: grid;
      gap: 8px;
    }
    .csvgen-preview-card {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px;
      background: #0b1220;
      display: grid;
      gap: 5px;
    }
    .csvgen-preview-name {
      color: var(--muted);
      font-size: 0.8rem;
    }
    .csvgen-preview-template {
      color: var(--text);
      font-size: 0.88rem;
      line-height: 1.35;
      white-space: pre-wrap;
    }
    .csvgen-note {
      color: var(--muted);
      font-size: 0.82rem;
    }
    .monitor {
      display: grid;
      gap: 14px;
    }
    .monitor-kpi-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 8px;
    }
    @media (max-width: 1100px) {
      .monitor-kpi-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }
    @media (max-width: 680px) {
      .monitor-kpi-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    .monitor-kpi-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px;
      min-height: 80px;
    }
    .monitor-kpi-label {
      color: var(--muted);
      font-size: 0.78rem;
      margin-bottom: 6px;
    }
    .monitor-kpi-value {
      font-size: 1.2rem;
      font-weight: 700;
    }
    .kpi-cyan { border-color: rgba(34, 211, 238, 0.55); }
    .kpi-yellow { border-color: rgba(245, 158, 11, 0.55); }
    .kpi-green { border-color: rgba(34, 197, 94, 0.55); }
    .kpi-red { border-color: rgba(239, 68, 68, 0.65); }
    .kpi-purple { border-color: rgba(168, 85, 247, 0.55); }
    .monitor-two-cols {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 12px;
      align-items: start;
    }
    @media (max-width: 980px) {
      .monitor-two-cols {
        grid-template-columns: 1fr;
      }
    }
    .monitor-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .monitor-title {
      margin: 0;
      font-size: 0.95rem;
      color: var(--text);
    }
    .state-list {
      display: grid;
      gap: 8px;
    }
    .state-item {
      display: grid;
      gap: 4px;
    }
    .state-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 0.82rem;
    }
    .state-bar-bg {
      height: 10px;
      border-radius: 999px;
      background: #0b1220;
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .state-bar-fill {
      height: 100%;
      border-radius: 999px;
      width: 0%;
    }
    .state-idle { background: #6b7280; }
    .state-greeting { background: #3b82f6; }
    .state-qualification { background: #22d3ee; }
    .state-handoff_pending { background: #f59e0b; }
    .state-handoff_active { background: #f97316; }
    .state-closed { background: #14532d; }
    .state-default { background: #94a3b8; }
    .response-gauge {
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 10px;
      background: #0b1220;
      display: grid;
      gap: 6px;
    }
    .response-level {
      font-size: 1rem;
      font-weight: 700;
    }
    .response-level.green { color: #86efac; }
    .response-level.yellow { color: #fde68a; }
    .response-level.red { color: #fecaca; }
    .monitor-health-wrap {
      display: grid;
      gap: 12px;
    }
    .system-gauge-wrap {
      display: grid;
      place-items: center;
      gap: 6px;
      padding: 8px;
    }
    .system-gauge-svg {
      width: 170px;
      height: 170px;
      transform: rotate(-90deg);
    }
    .system-gauge-bg {
      fill: none;
      stroke: #334155;
      stroke-width: 12;
    }
    .system-gauge-fg {
      fill: none;
      stroke: #22c55e;
      stroke-width: 12;
      stroke-linecap: round;
      stroke-dasharray: 439.82;
      stroke-dashoffset: 439.82;
      transition: stroke-dashoffset 0.8s ease, stroke 0.8s ease;
    }
    .system-gauge-center {
      margin-top: -130px;
      text-align: center;
      pointer-events: none;
    }
    .system-score {
      font-size: 2rem;
      font-weight: 800;
      line-height: 1;
    }
    .system-label {
      color: var(--muted);
      font-size: 0.85rem;
      margin-top: 4px;
    }
    .usage-bars {
      display: grid;
      gap: 8px;
    }
    .usage-row {
      display: grid;
      gap: 4px;
    }
    .usage-head {
      display: flex;
      justify-content: space-between;
      font-size: 0.82rem;
      color: var(--muted);
    }
    .usage-bg {
      height: 10px;
      border-radius: 999px;
      background: #0b1220;
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .usage-fill {
      height: 100%;
      border-radius: 999px;
      width: 0%;
      transition: width 0.6s ease;
    }
    .usage-fill.crm { background: #38bdf8; }
    .usage-fill.dlq { background: #ef4444; }
    .alerts-list {
      display: grid;
      gap: 6px;
    }
    .alert-item {
      border-radius: 8px;
      border: 1px solid var(--border);
      padding: 8px 10px;
      font-size: 0.84rem;
      background: #0b1220;
    }
    .funnel-card {
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 12px;
      display: grid;
      gap: 10px;
    }
    .funnel-list {
      display: grid;
      gap: 8px;
    }
    .funnel-item {
      display: grid;
      gap: 4px;
    }
    .funnel-head {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      color: var(--muted);
      font-size: 0.82rem;
    }
    .funnel-bar-bg {
      height: 12px;
      border-radius: 999px;
      background: #0b1220;
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .funnel-bar-fill {
      height: 100%;
      border-radius: 999px;
      width: 0%;
      transition: width 0.6s ease;
    }
    .conv-rates {
      display: grid;
      gap: 4px;
      color: var(--muted);
      font-size: 0.84rem;
    }
    .monitor-footer {
      text-align: right;
      color: var(--muted);
      font-size: 0.75rem;
    }
    :root {
      --brand-primary: #1a5276;
      --brand-accent: #2e86c1;
      --bg-base: #080c14;
      --bg-surface: #0d1420;
      --bg-elevated: #131d2e;
      --border: #1e2d42;
      --border-bright: #2a3f5c;
      --accent: var(--brand-accent);
      --accent-dim: #0099bb;
      --success: #00e676;
      --warning: #ffab00;
      --danger: #ff3d57;
      --purple: #b388ff;
      --text-primary: #e8f0fe;
      --text-secondary: #7b91b0;
      --text-dim: #3d5270;
      --bg: var(--bg-base);
      --card: var(--bg-surface);
      --text: var(--text-primary);
      --muted: var(--text-secondary);
      --warn: var(--warning);
      --info: var(--accent);
    }
    * {
      box-sizing: border-box;
      scrollbar-width: thin;
      scrollbar-color: var(--border-bright) var(--bg-base);
    }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text-primary);
      font-family: "Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background-color: var(--bg-base);
      background-image:
        linear-gradient(rgba(0, 212, 255, 0.03) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0, 212, 255, 0.03) 1px, transparent 1px);
      background-size: 32px 32px;
    }
    ::-webkit-scrollbar { width: 4px; height: 4px; }
    ::-webkit-scrollbar-track { background: var(--bg-base); }
    ::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 2px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--accent-dim); }

    .panel { background: transparent; }
    .content {
      max-width: 1400px;
      width: min(1400px, calc(100vw - 48px));
      margin: 0 auto;
      padding: 24px 0;
    }
    .dashboard, .campaigns, .templates, .csvgen, .conversations, .monitor, .audit-log, .placeholder {
      padding: 24px 0;
      animation: tabFade 0.15s ease;
    }
    [id$="-view"]:not(.hidden) { animation: tabFade 0.15s ease; }
    .hidden { display: none !important; }

    .center-wrap {
      min-height: 100vh;
      padding: 24px;
      display: grid;
      place-items: center;
    }
    .card, .metric-card, .health, .fsm-wrap, .mini-card, .campaign-run, .progress-card, .speed-card,
    .activity-card, .template-panel, .quality-card, .conv-search-card, .conv-summary-card, .conv-events-card,
    .csvgen-card, .monitor-card, .funnel-card, .monitor-kpi-card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 4px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
      transition: all 0.15s ease;
    }
    .metric-card:hover, .mini-card:hover, .monitor-kpi-card:hover, .template-panel:hover, .csvgen-card:hover {
      background: var(--bg-elevated);
      border-color: var(--border-bright);
    }
    .metric-card {
      border-left: 3px solid var(--accent);
      animation: fadeInUp 0.25s ease both;
    }
    .metric-grid .metric-card:nth-child(1) { animation-delay: 0.05s; }
    .metric-grid .metric-card:nth-child(2) { animation-delay: 0.1s; }
    .metric-grid .metric-card:nth-child(3) { animation-delay: 0.15s; }
    .metric-grid .metric-card:nth-child(4) { animation-delay: 0.2s; }
    .metric-grid .metric-card:nth-child(5) { animation-delay: 0.25s; }
    .metric-grid .metric-card:nth-child(6) { animation-delay: 0.3s; }
    .metric-grid .metric-card:nth-child(7) { animation-delay: 0.35s; }
    .metric-grid .metric-card:nth-child(8) { animation-delay: 0.4s; }
    .metric-card.dlq-alert {
      border-left-color: var(--danger);
      border-color: rgba(255, 61, 87, 0.45);
      background: rgba(255, 61, 87, 0.06);
    }
    .metric-label, .mini-label, .monitor-kpi-label {
      text-transform: uppercase;
      letter-spacing: 2px;
      font-size: 10px;
      color: var(--text-secondary);
      font-weight: 500;
    }
    .metric-value, .mini-value, .monitor-kpi-value, .conv-mini-value {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 2.5rem;
      line-height: 1.05;
      font-weight: 500;
      color: var(--text-primary);
    }
    .monitor-kpi-value { font-size: 1.8rem; }
    .mini-value { font-size: 1.6rem; }
    .conv-mini-value { font-size: 1.1rem; }

    .navbar {
      background: var(--brand-primary);
      border-bottom: 1px solid var(--border);
      padding: 0 24px;
      position: sticky;
      top: 0;
      z-index: 20;
      backdrop-filter: blur(6px);
    }
    .nav-top {
      min-height: 62px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .nav-brand {
      display: flex;
      align-items: baseline;
      flex-wrap: wrap;
      gap: 8px;
    }
    .brand-main {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      letter-spacing: 3px;
      font-weight: 500;
      font-size: 1rem;
      color: var(--text-primary);
    }
    .brand-sub {
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 1.2px;
      font-size: 11px;
      font-weight: 500;
    }
    .brand-logo {
      width: 30px;
      height: 30px;
      border-radius: 6px;
      object-fit: cover;
      border: 1px solid var(--border-bright);
    }
    .nav-status {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--text-secondary);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 1.2px;
    }
    .status-dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--success);
      box-shadow: 0 0 0 0 rgba(0, 230, 118, 0.6);
      animation: pulse 1.8s ease infinite;
    }
    .tabs {
      display: flex;
      gap: 22px;
      overflow-x: auto;
      padding: 0;
      border-top: 1px solid rgba(30, 45, 66, 0.55);
    }
    .tab {
      appearance: none;
      background: transparent;
      border: 0;
      border-bottom: 2px solid transparent;
      color: var(--text-secondary);
      border-radius: 0;
      padding: 12px 0;
      transition: all 0.2s ease;
      font-weight: 500;
    }
    .tab:hover { color: var(--text-primary); }
    .tab.active {
      color: var(--accent);
      border-bottom-color: var(--accent);
    }
    .tab.active::after {
      content: "";
      display: block;
      height: 0;
      transform: translateY(12px);
      animation: tabLine 0.2s ease;
    }

    .title, .monitor-title, .fsm-title, .snippet-title {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: var(--text-primary);
      letter-spacing: 0.8px;
      font-weight: 500;
      margin: 0;
    }
    .subtitle, .generated-at, .monitor-footer, .speed-current, .conv-search-msg, .csvgen-note {
      color: var(--text-secondary);
    }
    .generated-at { font-size: 11px; color: var(--text-dim); }

    label {
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 1.4px;
      font-size: 10px;
      font-weight: 500;
    }
    input, select, textarea, .template-select, .template-input, .template-textarea, .conv-search-input {
      background: var(--bg-base);
      color: var(--text-primary);
      border: 1px solid var(--border);
      border-radius: 4px;
      outline: none;
      font-family: "Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      transition: all 0.15s ease;
    }
    input:focus, select:focus, textarea:focus, .conv-search-input:focus, .template-select:focus, .template-input:focus, .template-textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 2px rgba(0, 212, 255, 0.1);
    }
    .template-textarea {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      min-height: 140px;
    }
    button {
      border-radius: 4px;
      transition: all 0.15s ease;
      font-weight: 600;
      font-family: "Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .btn-primary, .campaign-run-btn, .template-btn.primary, .csvgen-btn.primary, .conv-search-btn {
      background: var(--accent);
      color: #080c14;
      border: 1px solid transparent;
      padding: 10px 20px;
    }
    .btn-primary:hover, .campaign-run-btn:hover, .template-btn.primary:hover, .csvgen-btn.primary:hover, .conv-search-btn:hover {
      filter: brightness(1.1);
      transform: translateY(-1px);
    }
    .template-btn, .speed-btn, .activity-clear, .csvgen-btn {
      border: 1px solid var(--border-bright);
      background: transparent;
      color: var(--text-secondary);
    }
    .template-btn:hover, .speed-btn:hover, .activity-clear:hover, .csvgen-btn:hover {
      border-color: var(--accent);
      color: var(--accent);
    }
    .conv-control-btn.release {
      border: 1px solid var(--danger);
      color: var(--danger);
      background: rgba(255, 61, 87, 0.08);
    }
    .conv-control-btn.take {
      border: 1px solid var(--warning);
      color: #ffd280;
      background: rgba(255, 171, 0, 0.08);
    }
    .conv-control-btn:hover { transform: translateY(-1px); }
    .speed-btn.active {
      border-color: var(--accent);
      color: var(--accent);
      background: rgba(0, 212, 255, 0.08);
    }

    .toast-wrap {
      top: auto;
      right: 16px;
      bottom: 16px;
      z-index: 1200;
    }
    .toast {
      background: var(--bg-elevated);
      border: 1px solid var(--border-bright);
      border-left: 3px solid var(--accent);
      border-radius: 4px;
      color: var(--text-primary);
      animation: toastSlide 0.2s ease;
    }
    .toast.success { border-left-color: var(--success); }
    .toast.error { border-left-color: var(--danger); }
    .toast.info { border-left-color: var(--accent); }

    .progress-track, .usage-bg, .funnel-bar-bg, .fsm-bar-bg {
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      height: 6px;
      border-radius: 2px;
      overflow: hidden;
    }
    .progress-fill, .usage-fill, .funnel-bar-fill, .fsm-bar-fill {
      border-radius: 0;
    }
    .progress-fill.green { background: linear-gradient(90deg, #00c46a, var(--success)); }
    .progress-fill.yellow { background: linear-gradient(90deg, #ff7f11, var(--warning)); }
    .progress-fill.cyan { background: linear-gradient(90deg, var(--accent-dim), var(--accent)); }
    .usage-fill.crm { background: linear-gradient(90deg, var(--accent-dim), var(--accent)); }
    .usage-fill.dlq { background: linear-gradient(90deg, #d01b3e, var(--danger)); }

    .system-gauge-bg {
      stroke: rgba(43, 62, 89, 0.8);
      stroke-width: 12;
      fill: none;
    }
    .system-gauge-fg {
      stroke-width: 12;
      fill: none;
      stroke-linecap: round;
      stroke: var(--accent);
      transition: stroke-dashoffset 0.8s cubic-bezier(0.4, 0, 0.2, 1), stroke 0.3s ease;
    }
    .system-score {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 2rem;
      font-weight: 500;
      color: var(--text-primary);
    }
    .system-label {
      text-transform: uppercase;
      font-size: 10px;
      letter-spacing: 2px;
      color: var(--text-secondary);
    }
    .response-gauge {
      border: 1px solid var(--border);
      border-radius: 4px;
      background: var(--bg-elevated);
    }

    .wa-bubble, .conv-msg.outbound {
      background: #003d2e;
      border: 1px solid #005c40;
      border-radius: 8px;
      color: var(--text-primary);
      font-family: "Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
    }
    .conv-msg.inbound {
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      border-radius: 8px;
      font-family: "Outfit", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-size: 14px;
    }
    .wa-time, .conv-time, .wa-variant {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 10px;
      color: var(--text-dim);
    }

    .kpi-cyan { border-left: 3px solid var(--accent); }
    .kpi-yellow { border-left: 3px solid var(--warning); }
    .kpi-green { border-left: 3px solid var(--success); }
    .kpi-red { border-left: 3px solid var(--danger); }
    .kpi-purple { border-left: 3px solid var(--purple); }
    .monitor-kpi-card { padding: 12px; border-radius: 4px; }

    .monitor-two-cols, .templates-layout {
      gap: 16px;
    }

    .login-card {
      width: min(440px, calc(100vw - 32px));
      max-width: 440px;
      background: var(--bg-surface);
      border: 1px solid var(--border-bright);
      border-radius: 4px;
      padding: 28px 24px;
    }
    .login-logo {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-weight: 500;
      letter-spacing: 4px;
      color: var(--text-primary);
      font-size: 1.25rem;
      margin: 0 0 8px;
    }
    .login-subtitle {
      margin: 0 0 18px;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 2px;
      font-size: 10px;
    }
    #login-form .btn-primary {
      width: 100%;
      margin-top: 6px;
    }
    .error { color: var(--danger); min-height: 20px; }

    .spinner {
      border: 2px solid var(--border);
      border-top-color: var(--accent);
    }
    .dash-error, .campaign-result.error, .csvgen-result-error {
      border-radius: 4px;
      border: 1px solid rgba(255, 61, 87, 0.4);
      background: rgba(255, 61, 87, 0.08);
      color: #ff9aae;
    }
    .campaign-result.success {
      border-radius: 4px;
      border: 1px solid rgba(0, 230, 118, 0.45);
      background: rgba(0, 230, 118, 0.1);
      color: #93ffcb;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }
    @keyframes pulse {
      0% { transform: scale(1); opacity: 1; box-shadow: 0 0 0 0 rgba(0, 230, 118, 0.6); }
      70% { transform: scale(1.15); opacity: 0.9; box-shadow: 0 0 0 8px rgba(0, 230, 118, 0); }
      100% { transform: scale(1); opacity: 1; box-shadow: 0 0 0 0 rgba(0, 230, 118, 0); }
    }
    @keyframes tabFade {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes toastSlide {
      from { opacity: 0; transform: translateX(10px); }
      to { opacity: 1; transform: translateX(0); }
    }
    @keyframes tabLine {
      from { opacity: 0; transform: translateY(12px) scaleX(0.5); }
      to { opacity: 1; transform: translateY(12px) scaleX(1); }
    }
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes shimmer {
      from { background-position: -400px 0; }
      to { background-position: 400px 0; }
    }

    /* ─── UI/UX Pro Max — Accessibility & Interaction Layer ─── */

    /* Inline spinner for buttons */
    .btn-spinner {
      display: inline-block;
      width: 14px;
      height: 14px;
      margin-right: 8px;
      border: 2px solid rgba(8, 12, 20, 0.3);
      border-top-color: #080c14;
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
      vertical-align: middle;
      flex-shrink: 0;
    }
    button:disabled {
      opacity: 0.6;
      cursor: not-allowed !important;
    }
    input:disabled, select:disabled, textarea:disabled {
      opacity: 0.5;
      cursor: not-allowed !important;
    }

    /* Cursor pointer on all interactive elements */
    button, [role="button"], .tab, .chip, .snippet-item, .speed-btn,
    .template-btn, .csvgen-btn, .activity-clear, .conv-control-btn,
    .campaign-run-btn, label[for], .csvgen-drop { cursor: pointer; }

    /* Focus rings — visible keyboard navigation */
    :focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
      border-radius: 4px;
    }

    /* Minimum touch target heights (44px) */
    button, .tab, input, select, textarea {
      min-height: 44px;
    }
    .tab { min-height: 0; padding: 14px 0; }
    .speed-btn, .template-btn, .activity-clear, .csvgen-btn,
    .conv-control-btn { min-height: 44px; }

    /* Input font-size 16px — prevent iOS auto-zoom */
    input, select, textarea,
    .template-select, .template-input, .template-textarea,
    .conv-search-input {
      font-size: 16px;
    }

    /* Navbar accent line for depth */
    .navbar::before {
      content: "";
      display: block;
      height: 2px;
      background: linear-gradient(90deg, transparent, var(--accent), var(--purple), transparent);
      opacity: 0.5;
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
    }
    .navbar { position: relative; }

    /* Enhanced card hover — elevation system */
    .metric-card:hover, .mini-card:hover, .monitor-kpi-card:hover,
    .template-panel:hover, .csvgen-card:hover, .monitor-card:hover,
    .funnel-card:hover {
      transform: translateY(-1px);
      box-shadow: 0 4px 16px rgba(0, 212, 255, 0.08), 0 1px 4px rgba(0, 0, 0, 0.4);
    }

    /* Button active state — subtle press feedback */
    button:active { transform: translateY(0) scale(0.98); }
    .btn-primary:active, .campaign-run-btn:active,
    .template-btn.primary:active, .csvgen-btn.primary:active,
    .conv-search-btn:active { transform: translateY(0); filter: brightness(0.95); }

    /* Toast container — screen-reader live region */
    .toast-wrap {
      pointer-events: none;
    }
    .toast { pointer-events: all; }

    /* Skeleton loading state */
    .skeleton {
      background: linear-gradient(
        90deg,
        var(--bg-elevated) 25%,
        var(--border-bright) 50%,
        var(--bg-elevated) 75%
      );
      background-size: 400px 100%;
      animation: shimmer 1.5s infinite;
      border-radius: 4px;
      color: transparent !important;
    }
    .skeleton * { visibility: hidden; }

    /* Improved tab indicator — smoother active state */
    .tab {
      position: relative;
      font-size: 13px;
      letter-spacing: 0.3px;
      white-space: nowrap;
    }
    .tab.active {
      font-weight: 600;
    }

    /* Section title visual hierarchy */
    .section-heading {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid var(--border);
    }
    .section-heading-text {
      font-family: "DM Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 3px;
      text-transform: uppercase;
      color: var(--text-secondary);
    }
    .section-heading-line {
      flex: 1;
      height: 1px;
      background: linear-gradient(90deg, var(--border), transparent);
    }

    /* Campaign run button icon */
    .campaign-run-btn {
      gap: 8px;
      letter-spacing: 0.5px;
    }

    /* Improved metric value — tabular numbers */
    .metric-value, .mini-value, .monitor-kpi-value, .conv-mini-value {
      font-variant-numeric: tabular-nums;
    }

    /* Chip hover states */
    .chip:hover, .csvgen-chip:hover {
      border-color: var(--accent);
      color: var(--accent);
      transition: all 0.15s ease;
    }
    .chip-found { border-color: rgba(0, 230, 118, 0.4); color: #93ffcb; }
    .chip-missing { border-color: rgba(255, 61, 87, 0.5); color: #ff9aae; background: rgba(255, 61, 87, 0.08); }

    /* Conversations empty state */
    .conv-empty-state {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px 20px;
      gap: 8px;
      text-align: center;
    }
    .conv-empty-icon {
      font-size: 2rem;
      color: var(--border-bright);
      line-height: 1;
      margin-bottom: 4px;
    }
    .conv-empty-title {
      font-size: 0.92rem;
      font-weight: 600;
      color: var(--text-secondary);
    }
    .conv-empty-hint {
      font-size: 0.82rem;
      color: var(--text-dim);
    }

    /* Log items — alternating subtle rows */
    .activity-item:nth-child(odd) {
      background: rgba(255, 255, 255, 0.015);
    }

    /* Drag-over drop zone — more visible feedback */
    .csvgen-drop {
      transition: all 0.2s ease;
      min-height: 80px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .csvgen-drop:hover {
      border-color: var(--accent);
      background: rgba(0, 212, 255, 0.1);
      color: var(--text-primary);
    }

    /* Conv bubble improvements */
    .conv-msg { line-height: 1.45; }
    .wa-message { line-height: 1.45; }

    /* Login card glow */
    .login-card {
      box-shadow: 0 0 0 1px var(--border-bright),
                  0 8px 40px rgba(0, 0, 0, 0.5),
                  0 0 60px rgba(0, 212, 255, 0.04);
    }

    /* Activity log structured entries */
    .log-ts {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 0.75rem;
      color: var(--text-dim);
      margin-right: 8px;
      flex-shrink: 0;
    }
    .log-sym {
      font-family: "DM Mono", ui-monospace, monospace;
      font-weight: 700;
      margin-right: 8px;
      flex-shrink: 0;
    }
    .log-ok-sym { color: var(--success); }
    .log-fail-sym { color: var(--danger); }
    .log-body { font-size: 0.84rem; color: var(--text-secondary); }
    .activity-item {
      display: flex;
      align-items: baseline;
      gap: 0;
      flex-wrap: wrap;
    }
    .activity-item.log-ok { border-left: 2px solid rgba(0, 230, 118, 0.3); }
    .activity-item.log-fail { border-left: 2px solid rgba(255, 61, 87, 0.4); }

    /* Alert level colors */
    .alert-error { border-left: 3px solid var(--danger); color: #ff9aae; }
    .alert-warn { border-left: 3px solid var(--warning); color: #ffd280; }
    .alert-info { border-left: 3px solid var(--accent); color: var(--text-secondary); }
    .alert-ok { border-left: 3px solid var(--success); color: #93ffcb; }

    /* Checklist items */
    .check-ok { color: var(--success); }
    .check-fail { color: var(--danger); }

    /* Prefers reduced motion — disable all animations */
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
      }
      .status-dot { animation: none !important; }
      .quality-dot.red { animation: none !important; }
    }

    /* Response gauge — visual progress bar + threshold bands */
    .response-gauge-bar-track {
      height: 8px;
      border-radius: 3px;
      background: var(--bg-base);
      border: 1px solid var(--border);
      overflow: hidden;
    }
    .response-gauge-bar-fill {
      height: 100%;
      border-radius: 3px;
      transition: width 0.6s ease, background 0.3s ease;
    }
    .response-gauge-bands {
      display: flex;
      gap: 3px;
      margin-top: 6px;
    }
    .response-band {
      flex: 1;
      height: 3px;
      border-radius: 2px;
      opacity: 0.35;
    }
    .response-band.green { background: var(--success); }
    .response-band.yellow { background: var(--warning); }
    .response-band.red { background: var(--danger); }
    .response-gauge-legend {
      font-size: 10px;
      color: var(--text-dim);
      margin-top: 4px;
      letter-spacing: 0.3px;
    }

    /* Conv rates — badge row layout */
    .conv-rates {
      display: grid;
      gap: 6px;
      border-top: 1px solid var(--border);
      padding-top: 10px;
      margin-top: 4px;
    }
    .conv-rate-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 0.84rem;
      color: var(--text-secondary);
    }
    .conv-rate-badge {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 0.75rem;
      font-variant-numeric: tabular-nums;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid var(--border-bright);
      background: var(--bg-elevated);
      color: var(--text-primary);
      min-width: 52px;
      text-align: center;
      flex-shrink: 0;
    }
    .conv-rate-badge.high { border-color: rgba(0,230,118,0.4); color: #93ffcb; background: rgba(0,230,118,0.06); }
    .conv-rate-badge.mid { border-color: rgba(255,171,0,0.4); color: #ffd280; background: rgba(255,171,0,0.06); }
    .conv-rate-badge.low { border-color: rgba(255,61,87,0.35); color: #ff9aae; background: rgba(255,61,87,0.06); }

    /* CSV file info card */
    .csvgen-file-card {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      background: var(--bg-elevated);
      border: 1px solid var(--border-bright);
      border-radius: 6px;
      flex-wrap: wrap;
    }
    .csvgen-file-icon {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 0.9rem;
      color: var(--accent);
      flex-shrink: 0;
      opacity: 0.85;
    }
    .csvgen-file-name {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 0.84rem;
      color: var(--text-primary);
      flex: 1;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .csvgen-file-badges {
      display: flex;
      gap: 6px;
      flex-wrap: wrap;
      flex-shrink: 0;
    }
    .csvgen-file-badge {
      font-size: 0.75rem;
      font-variant-numeric: tabular-nums;
      padding: 2px 8px;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--bg-base);
      color: var(--text-secondary);
    }

    /* Quality dot — pulse animation when red */
    @keyframes pulse-danger {
      0%   { box-shadow: 0 0 0 0 rgba(255,61,87,0.6); }
      70%  { box-shadow: 0 0 0 6px rgba(255,61,87,0); }
      100% { box-shadow: 0 0 0 0 rgba(255,61,87,0); }
    }
    .quality-dot.red { animation: pulse-danger 1.5s ease infinite; }

    /* Speed buttons — segmented control */
    .speed-buttons {
      background: var(--bg-base);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 3px;
      display: inline-flex;
      gap: 2px;
      flex-wrap: nowrap;
    }
    .speed-btn {
      flex: 1;
      border: 1px solid transparent !important;
      border-radius: 4px !important;
      background: transparent !important;
      color: var(--text-secondary) !important;
    }
    .speed-btn:hover {
      border-color: var(--border-bright) !important;
      color: var(--text-primary) !important;
    }
    .speed-btn.active {
      background: rgba(0,212,255,0.1) !important;
      border-color: var(--accent) !important;
      color: var(--accent) !important;
    }

    /* Stat chip — tabular nums + color context */
    .stat-chip-value { font-variant-numeric: tabular-nums; }
    .stat-chip-value.warn { color: var(--warning); }
    .stat-chip-value.danger { color: var(--danger); }

    /* Live clock in nav */
    .nav-clock {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 11px;
      color: var(--text-dim);
      letter-spacing: 1px;
    }

    /* Health description text — replaces inline style */
    .health-desc {
      color: var(--text-secondary);
      font-size: 0.88rem;
      margin-top: 3px;
      line-height: 1.45;
    }

    /* Quality checks — custom pill list */
    .checks-list {
      display: grid;
      gap: 5px;
      padding: 0;
      margin: 0;
      list-style: none;
    }
    .checks-list li {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.84rem;
      color: var(--text-secondary);
    }
    .check-sym {
      width: 18px;
      height: 18px;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      font-weight: 700;
      flex-shrink: 0;
    }
    .check-sym.ok   { background: rgba(0,230,118,0.12); color: var(--success); border: 1px solid rgba(0,230,118,0.3); }
    .check-sym.fail { background: rgba(255,61,87,0.1);  color: var(--danger);  border: 1px solid rgba(255,61,87,0.3); }

    /* Alert items — level tag prefix */
    .alert-level-tag {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 9px;
      letter-spacing: 1.5px;
      text-transform: uppercase;
      margin-right: 8px;
      padding: 1px 5px;
      border-radius: 3px;
      vertical-align: middle;
    }
    .alert-error .alert-level-tag { background: rgba(255,61,87,0.15);  color: var(--danger); }
    .alert-warn  .alert-level-tag { background: rgba(255,171,0,0.15);  color: var(--warning); }
    .alert-info  .alert-level-tag { background: rgba(0,212,255,0.12);  color: var(--accent); }
    .alert-ok    .alert-level-tag { background: rgba(0,230,118,0.12);  color: var(--success); }

    /* csvgen table — sticky header + uppercase labels */
    .csvgen-table th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: var(--bg-elevated);
      border-bottom: 1px solid var(--border-bright);
      text-transform: uppercase;
      letter-spacing: 1.5px;
      font-size: 9px;
      color: var(--text-secondary);
      font-weight: 600;
    }

    /* Universal placeholder color */
    ::placeholder { color: var(--text-dim); opacity: 1; }

    /* Hide tab overflow scrollbar */
    .tabs { scrollbar-width: none; }
    .tabs::-webkit-scrollbar { display: none; }

    /* Snippet item hover */
    .snippet-item:hover {
      border-color: var(--accent);
      color: var(--accent);
      background: rgba(0, 212, 255, 0.04);
      transition: all 0.15s ease;
    }

    /* Quality dot colored glow rings */
    .quality-dot.green  { box-shadow: 0 0 0 3px rgba(0,230,118,0.18); }
    .quality-dot.yellow { box-shadow: 0 0 0 3px rgba(255,171,0,0.18); }

    /* Inject banner — AUTO tag prefix */
    .inject-banner::before {
      content: "AUTO";
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 9px;
      letter-spacing: 1.5px;
      background: rgba(168, 85, 247, 0.2);
      color: #d8b4fe;
      padding: 1px 5px;
      border-radius: 3px;
      margin-right: 8px;
      vertical-align: middle;
    }

    /* Conv header — left-border color per column */
    .col-phone   { border-left: 3px solid var(--accent) !important; }
    .col-state   { border-left: 3px solid var(--warning) !important; }
    .col-control { border-left: 3px solid var(--success) !important; }
    .col-date    { border-left: 3px solid var(--text-dim) !important; }

    /* Conv mini-stat — KPI colors */
    .conv-mini-stat.kpi-cyan   { border-left: 3px solid var(--accent); }
    .conv-mini-stat.kpi-green  { border-left: 3px solid var(--success); }
    .conv-mini-stat.kpi-yellow { border-left: 3px solid var(--warning); }
    .conv-mini-stat.kpi-purple { border-left: 3px solid var(--purple); }

    /* Template character counter */
    .template-char-count {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 10px;
      color: var(--text-dim);
      text-align: right;
      margin-top: 4px;
      letter-spacing: 0.5px;
      font-variant-numeric: tabular-nums;
    }
    .template-char-count.warn   { color: var(--warning); }
    .template-char-count.danger { color: var(--danger); }

    /* Utility: tabular numbers */
    .tnum { font-variant-numeric: tabular-nums; }

    /* Template syntax errors list */
    .template-syntax-errors {
      margin-top: 6px;
      display: grid;
      gap: 4px;
    }
    .syntax-error-item {
      font-family: "DM Mono", ui-monospace, monospace;
      font-size: 0.78rem;
      color: #ff9aae;
      background: rgba(255,61,87,0.08);
      border: 1px solid rgba(255,61,87,0.25);
      border-radius: 4px;
      padding: 4px 8px;
    }
    .audit-controls {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .audit-table-wrap {
      overflow-x: auto;
      border: 1px solid var(--border);
      border-radius: 4px;
    }
    .audit-table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.84rem;
    }
    .audit-table th, .audit-table td {
      border-bottom: 1px solid var(--border);
      padding: 8px;
      text-align: left;
      vertical-align: top;
    }
    .audit-table th {
      color: var(--text-secondary);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.6px;
    }
  </style>
</head>
<body>
  <div id="login-screen" class="center-wrap">
    <div class="card login-card">
      <h2 class="login-logo brand-name">Marca</h2>
      <p class="login-subtitle">SISTEMA DE CONTROL OPERATIVO</p>
      <h3 class="title">Acceso Administrador</h3>
      <p class="subtitle">Inicia sesión para acceder al panel de <span class="brand-admin-title">Panel Admin</span>.</p>
      <form id="login-form">
        <label for="username">Usuario</label>
        <input id="username" name="username" type="text" autocomplete="username" required />
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required />
        <div id="login-2fa-wrap" class="hidden">
          <label for="login-2fa-code">Código de autenticación (6 dígitos)</label>
          <input id="login-2fa-code" name="login_2fa_code" type="text" inputmode="numeric" maxlength="8" autocomplete="one-time-code" />
        </div>
        <button class="btn-primary" type="submit">Entrar</button>
      </form>
      <div id="login-error" class="error"></div>
    </div>
  </div>

  <div id="panel-screen" class="panel hidden">
    <header class="navbar">
      <div class="nav-top">
        <div class="nav-brand">
          <img id="brand-logo" class="brand-logo hidden" alt="Logo de marca" />
          <span class="brand-main brand-name">Marca</span>
          <span class="brand-sub brand-admin-title">Panel Admin</span>
          <span id="brand-support-phone" class="brand-sub hidden"></span>
        </div>
        <div class="nav-status">
          <span class="status-dot" role="status" aria-label="Sistema operativo"></span>
          <span>Sistema OK</span>
          <span id="nav-clock" class="nav-clock" aria-hidden="true"></span>
        </div>
      </div>
      <nav class="tabs" id="tabs" role="tablist" aria-label="Secciones del panel">
        <button class="tab active" data-tab="dashboard" type="button" role="tab" aria-selected="true" tabindex="0">Dashboard</button>
        <button class="tab" data-tab="campanas" type="button" role="tab" aria-selected="false" tabindex="-1">Campañas</button>
        <button class="tab" data-tab="templates" type="button" role="tab" aria-selected="false" tabindex="-1">Templates</button>
        <button class="tab" data-tab="generador_csv" type="button" role="tab" aria-selected="false" tabindex="-1">Generador CSV</button>
        <button class="tab" data-tab="conversaciones" type="button" role="tab" aria-selected="false" tabindex="-1">Conversaciones</button>
        <button class="tab" data-tab="monitor" type="button" role="tab" aria-selected="false" tabindex="-1">Monitor</button>
        <button class="tab" data-tab="knowledge" type="button" role="tab" aria-selected="false" tabindex="-1">Base de conocimiento</button>
        <button class="tab" data-tab="security" type="button" role="tab" aria-selected="false" tabindex="-1">Seguridad</button>
        <button class="tab" data-tab="audit_log" type="button" role="tab" aria-selected="false" tabindex="-1">Registro actividad</button>
      </nav>
    </header>
    <main class="content">
      <section id="dashboard-view" class="dashboard hidden" aria-label="Dashboard operativo">
        <div class="section-heading">
          <span class="section-heading-text">Dashboard Operativo</span>
          <span class="section-heading-line"></span>
          <div id="dashboard-spinner" class="spinner hidden" aria-label="Cargando dashboard"></div>
        </div>
        <div id="dashboard-error" class="dash-error hidden"></div>
        <div id="dashboard-cards" class="metric-grid"></div>
        <div id="dashboard-health" class="health" role="status"></div>
        <div id="dashboard-fsm" class="fsm-wrap"></div>
        <div id="dashboard-generated-at" class="generated-at" aria-live="polite"></div>
      </section>

      <section id="campaigns-view" class="campaigns hidden" aria-label="Gestión de campañas">
        <div class="section-heading">
          <span class="section-heading-text">Campañas Outbound</span>
          <span class="section-heading-line"></span>
          <div id="campaigns-spinner" class="spinner hidden" aria-label="Cargando campañas"></div>
        </div>
        <div id="campaigns-error" class="dash-error hidden"></div>
        <div id="campaigns-worker-state" class="mini-grid"></div>
        <div class="campaign-run">
          <button id="run-worker-btn" class="campaign-run-btn" type="button">
            Ejecutar Worker Ahora
          </button>
          <div id="campaign-run-result" class="campaign-result hidden"></div>
        </div>
        <div class="progress-card">
          <div class="goal-row">
            <label for="campaign-goal-input" style="margin:0;">Objetivo del día</label>
            <input id="campaign-goal-slider" type="range" min="1" max="2000" step="1" />
            <input id="campaign-goal-input" type="number" min="1" step="1" />
          </div>
          <div class="progress-track">
            <div id="campaign-progress-fill" class="progress-fill green"></div>
          </div>
          <div id="campaign-progress-text" class="speed-current">0 / 100 mensajes (0%)</div>
        </div>
        <div class="speed-card">
          <div class="speed-buttons">
            <button class="speed-btn" data-speed="slow" type="button">▾ Lento</button>
            <button class="speed-btn" data-speed="normal" type="button">◆ Normal</button>
            <button class="speed-btn" data-speed="fast" type="button">▲ Rápido</button>
          </div>
          <div id="speed-current" class="speed-current">Velocidad actual: Normal</div>
        </div>
        <div class="activity-card">
          <div class="activity-head">
            <strong>Log de actividad</strong>
            <button id="clear-activity-log-btn" class="activity-clear" type="button">Limpiar log</button>
          </div>
          <ul id="campaign-activity-log" class="activity-log"></ul>
        </div>
      </section>

      <section id="templates-view" class="templates hidden" aria-label="Editor de templates">
        <div class="section-heading">
          <span class="section-heading-text">Editor de Templates</span>
          <span class="section-heading-line"></span>
        </div>
        <div class="templates-layout">
          <section class="template-panel">
            <div>
              <label for="template-campaign-type">Tipo de campaña</label>
              <select id="template-campaign-type" class="template-select">
                <option value="lost">Lead perdido / sin respuesta</option>
                <option value="quoted">Lead cotizado / asignado</option>
                <option value="post_visit">Cita atendida / post-visita</option>
                <option value="service">Seguimiento de servicio</option>
              </select>
            </div>

            <div class="template-row">
              <div>
                <label for="template-test-name">Nombre</label>
                <input id="template-test-name" class="template-input" type="text" value="Carlos Mendoza" />
              </div>
              <div>
                <label for="template-test-vehicle">Vehículo</label>
                <input id="template-test-vehicle" class="template-input" type="text" value="Freightliner Cascadia 2020" />
              </div>
              <div>
                <label for="template-test-branch">Sucursal</label>
                <input id="template-test-branch" class="template-input" type="text" value="Querétaro" />
              </div>
              <div>
                <label for="template-test-notes">Notas</label>
                <input id="template-test-notes" class="template-input" type="text" value="" />
              </div>
            </div>

            <div>
              <label for="template-editor">Template</label>
              <textarea id="template-editor" class="template-textarea" aria-describedby="template-char-count"></textarea>
              <div id="template-char-count" class="template-char-count" aria-live="polite">0 / 250 chars</div>
            </div>

            <div>
              <div class="snippet-title">Variables</div>
              <div class="chips-wrap" id="template-variable-chips"></div>
            </div>

            <div>
              <div class="snippet-title">Biblioteca de snippets</div>
              <div class="snippet-grid" id="template-snippets"></div>
            </div>

            <div class="template-actions">
              <button id="template-preview-btn" class="template-btn primary" type="button">Vista Previa</button>
              <button id="template-variants-btn" class="template-btn primary" type="button">Generar 5 Variantes</button>
              <button id="template-copy-raw-btn" class="template-btn" type="button">Copiar Template</button>
              <button id="template-copy-preview-btn" class="template-btn" type="button">Copiar Preview</button>
            </div>
          </section>

          <section class="template-panel">
            <div class="quality-card">
              <div class="quality-head">
                <span id="template-quality-dot" class="quality-dot green"></span>
                <strong id="template-quality-label">Calidad Alta</strong>
              </div>
              <ul id="template-checks-list" class="checks-list"></ul>
            </div>

            <div id="template-stats-bar" class="stats-bar"></div>

            <div id="template-inject-banner" class="inject-banner hidden">
              El sistema agregará presentación automáticamente: "Hola, soy Raúl Rodríguez de {company_name}."
            </div>

            <div>
              <div class="snippet-title">Preview de WhatsApp</div>
              <div id="template-bubbles" class="bubble-list"></div>
            </div>

            <div class="examples-grid">
              <div class="example-card good">
                <strong>BIEN</strong><br />
                [Hola|Buenas|Qué tal] {nombre}, [te escribo|te contacto] de {company_name}.<br />
                [Recuerdo que|Hace un tiempo] preguntaste por el {vehiculo}.<br />
                ¿[Sigues interesado|Todavía lo consideras|Ya resolviste]?
              </div>
              <div class="example-card bad">
                <strong>MAL</strong><br />
                Hola, promoción increíble y descuento total gratis para todos los modelos disponibles hoy mismo sin preguntar nada ni personalizar ni mencionar vehículo
              </div>
            </div>
          </section>
        </div>
      </section>

      <section id="csvgen-view" class="csvgen hidden" aria-label="Generador CSV con IA">
        <div class="section-heading">
          <span class="section-heading-text">Generador CSV con IA</span>
          <span class="section-heading-line"></span>
        </div>
        <section class="csvgen-card">
          <div class="csvgen-note">
            Sube tu exportación de Monday.com. La IA leerá el Resumen, Vehículo y Nombre de cada prospecto y generará un template personalizado con spintax para cada uno.
          </div>

          <div id="csvgen-drop" class="csvgen-drop">
            Arrastra y suelta tu CSV aquí o haz click para seleccionar archivo
            <input id="csvgen-file-input" type="file" accept=".csv,text/csv" class="hidden" />
          </div>

          <div id="csvgen-file-info" class="csvgen-fileinfo hidden"></div>

          <div id="csvgen-table-wrap" class="csvgen-table-wrap hidden">
            <table class="csvgen-table">
              <thead id="csvgen-table-head"></thead>
              <tbody id="csvgen-table-body"></tbody>
            </table>
          </div>

          <div>
            <div class="snippet-title">Columnas detectadas</div>
            <div id="csvgen-columns-chips" class="csvgen-chips"></div>
          </div>

          <div class="csvgen-actions">
            <button id="csvgen-generate-btn" class="csvgen-btn primary" type="button">Generar Templates con IA</button>
            <button id="csvgen-download-btn" class="csvgen-btn hidden" type="button">Descargar CSV con Templates</button>
            <button id="csvgen-reset-btn" class="csvgen-btn hidden" type="button">Nueva carga</button>
          </div>

          <div class="csvgen-note">Columnas mínimas: nombre, vehiculo, resumen, template</div>
          <div id="csvgen-error" class="csvgen-result-error hidden"></div>
        </section>

        <section id="csvgen-preview-section" class="csvgen-card hidden">
          <h3 class="monitor-title">Preview de templates generados</h3>
          <div id="csvgen-preview-list" class="csvgen-preview-list"></div>
        </section>
      </section>

      <section id="conversations-view" class="conversations hidden" aria-label="Visor de conversaciones">
        <div class="section-heading">
          <span class="section-heading-text">Visor de Conversaciones</span>
          <span class="section-heading-line"></span>
        </div>
        <section class="conv-search-card">
          <div class="conv-search-row">
            <div>
              <label for="conv-lead-id-input">Lead ID</label>
              <input
                id="conv-lead-id-input"
                class="conv-search-input"
                type="text"
                placeholder="ej. 00000000-0000-0000-0000-000000000123"
              />
            </div>
            <button id="conv-search-btn" class="conv-search-btn" type="button">Buscar</button>
          </div>
          <div id="conv-search-msg" class="conv-search-msg"></div>
        </section>

        <section id="conv-summary-card" class="conv-summary-card hidden">
          <div id="conv-header-row" class="conv-header-row"></div>
          <div id="conv-stats-grid" class="conv-stats-grid"></div>
          <div class="conv-control-row">
            <button id="conv-control-btn" class="conv-control-btn take" type="button">⊕ Tomar Control</button>
          </div>
        </section>

        <section class="conv-events-card">
          <div class="snippet-title">Conversación</div>
          <div id="conv-events-scroll" class="conv-events-scroll"></div>
        </section>
      </section>

      <section id="monitor-view" class="monitor hidden" aria-label="Monitor del sistema">
        <div class="section-heading">
          <span class="section-heading-text">Monitor del Sistema</span>
          <span class="section-heading-line"></span>
          <div id="monitor-spinner" class="spinner hidden" aria-label="Cargando monitor"></div>
        </div>
        <div id="monitor-error" class="dash-error hidden"></div>

        <section id="monitor-kpi-grid" class="monitor-kpi-grid"></section>

        <section class="monitor-two-cols">
          <div class="monitor-health-wrap">
            <section class="monitor-card">
              <h3 class="monitor-title">Estado de Sesiones</h3>
              <div id="monitor-state-list" class="state-list"></div>
            </section>
            <section class="monitor-card">
              <h3 class="monitor-title">Tiempo de respuesta</h3>
              <div id="monitor-response-gauge" class="response-gauge"></div>
            </section>
          </div>

          <div class="monitor-health-wrap">
            <section class="monitor-card">
              <h3 class="monitor-title">Salud del sistema</h3>
              <div class="system-gauge-wrap">
                <svg class="system-gauge-svg" viewBox="0 0 160 160" aria-label="System score">
                  <circle class="system-gauge-bg" cx="80" cy="80" r="70"></circle>
                  <circle id="monitor-system-gauge-fg" class="system-gauge-fg" cx="80" cy="80" r="70"></circle>
                </svg>
                <div class="system-gauge-center">
                  <div id="monitor-system-score" class="system-score">0</div>
                  <div id="monitor-system-label" class="system-label">Crítico</div>
                </div>
              </div>
              <div class="usage-bars">
                <div class="usage-row">
                  <div class="usage-head"><span>CRM Sync</span><span id="monitor-usage-crm-label">0%</span></div>
                  <div class="usage-bg"><div id="monitor-usage-crm-fill" class="usage-fill crm"></div></div>
                </div>
                <div class="usage-row">
                  <div class="usage-head"><span>DLQ</span><span id="monitor-usage-dlq-label">0%</span></div>
                  <div class="usage-bg"><div id="monitor-usage-dlq-fill" class="usage-fill dlq"></div></div>
                </div>
              </div>
              <div id="monitor-alerts-list" class="alerts-list"></div>
            </section>
          </div>
        </section>

        <section class="funnel-card">
          <h3 class="monitor-title">Funnel FSM — Conversión por Estado</h3>
          <div id="monitor-funnel-list" class="funnel-list"></div>
          <div id="monitor-conv-rates" class="conv-rates"></div>
          <div id="monitor-footer" class="monitor-footer">Actualizado: --:--:-- · auto-refresh cada 10s</div>
        </section>
      </section>

      <section id="knowledge-view" class="csvgen hidden" aria-label="Base de conocimiento">
        <div class="section-heading">
          <span class="section-heading-text">Base de conocimiento</span>
          <span class="section-heading-line"></span>
          <div id="knowledge-spinner" class="spinner hidden" aria-label="Cargando fuentes"></div>
        </div>
        <section class="csvgen-card">
          <form id="knowledge-upload-form" class="csvgen-actions" style="align-items:flex-end;">
            <div style="flex:1; min-width:220px;">
              <label for="knowledge-source-label">Nombre de fuente</label>
              <input id="knowledge-source-label" class="template-input" type="text" placeholder="Ej. Catálogo Q1 2026" required />
            </div>
            <div style="flex:1; min-width:220px;">
              <label for="knowledge-file-input">Documento (PDF/MD/TXT/DOCX)</label>
              <input id="knowledge-file-input" class="template-input" type="file" accept=".pdf,.md,.txt,.docx" required />
            </div>
            <button id="knowledge-upload-btn" class="csvgen-btn primary" type="submit">Subir documento</button>
          </form>
          <div id="knowledge-status" class="csvgen-note">Sin operaciones recientes.</div>
        </section>
        <section class="csvgen-card">
          <h3 class="monitor-title">Fuentes cargadas</h3>
          <div id="knowledge-sources-list" class="csvgen-preview-list"></div>
        </section>
      </section>

      <section id="audit-log-view" class="audit-log hidden" aria-label="Registro de actividad">
        <div class="section-heading">
          <span class="section-heading-text">Registro de actividad</span>
          <span class="section-heading-line"></span>
        </div>
        <section class="csvgen-card">
          <div class="audit-controls">
            <input id="audit-action-filter" class="template-input" type="text" placeholder="Filtrar por acción (ej. login_success)" style="max-width:320px;" />
            <button id="audit-filter-btn" class="csvgen-btn" type="button">Filtrar</button>
            <button id="audit-clear-btn" class="csvgen-btn" type="button">Limpiar</button>
          </div>
          <div class="audit-table-wrap">
            <table class="audit-table">
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Acción</th>
                  <th>Recurso</th>
                  <th>IP</th>
                </tr>
              </thead>
              <tbody id="audit-log-body"></tbody>
            </table>
          </div>
          <div class="audit-controls" style="margin-top:10px;">
            <button id="audit-prev-btn" class="csvgen-btn" type="button">Anterior</button>
            <button id="audit-next-btn" class="csvgen-btn" type="button">Siguiente</button>
            <span id="audit-page-label" class="csvgen-note">Página 1</span>
          </div>
        </section>
      </section>

      <section id="security-view" class="csvgen hidden" aria-label="Seguridad">
        <div class="section-heading">
          <span class="section-heading-text">Seguridad</span>
          <span class="section-heading-line"></span>
        </div>
        <section class="csvgen-card">
          <div id="security-2fa-status" class="csvgen-note">2FA: Inactivo</div>
          <div class="csvgen-actions">
            <button id="security-2fa-setup-btn" class="csvgen-btn primary" type="button">Activar 2FA</button>
          </div>
          <div id="security-2fa-setup-wrap" class="hidden">
            <p class="csvgen-note">Escanea este QR en Google Authenticator/Authy y confirma con un código.</p>
            <img id="security-2fa-qr" alt="QR 2FA" style="max-width:220px; border:1px solid var(--border); border-radius:4px; padding:6px; background:#fff;" />
            <div class="csvgen-note">Secret: <code id="security-2fa-secret"></code></div>
            <div style="max-width:320px; margin-top:8px;">
              <label for="security-2fa-code">Ingresa el código de tu app</label>
              <input id="security-2fa-code" class="template-input" type="text" inputmode="numeric" maxlength="8" />
            </div>
            <div class="csvgen-actions">
              <button id="security-2fa-confirm-btn" class="csvgen-btn primary" type="button">Confirmar y activar</button>
            </div>
          </div>
        </section>
      </section>

      <div id="tab-placeholder" class="placeholder hidden">Selecciona una pestaña para continuar.</div>
    </main>
  </div>

  <div id="toast-wrap" class="toast-wrap" aria-live="polite" aria-atomic="false"></div>

  <script>
    const TOKEN_KEY = "raul_admin_token";
    const DASHBOARD_REFRESH_MS = 15000;
    const CAMPAIGNS_REFRESH_MS = 30000;
    const CAMPAIGN_GOAL_KEY = "raul_campaign_goal";
    const SPEED_KEY = "raul_speed";
    const TEMPLATE_DEBOUNCE_MS = 300;
    const MONITOR_REFRESH_MS = 10000;
    const MONITOR_GAUGE_CIRCUMFERENCE = 439.82;
    const TEMPLATE_DEFAULT_BOT_NAME = "Raúl Rodríguez";
    const BRAND_DEFAULTS = {
      name: "Marca",
      slug: "brand",
      logo_url: "",
      primary_color: "#1a5276",
      accent_color: "#2e86c1",
      admin_title: "Panel Admin",
      support_phone: "",
    };

    const loginScreen = document.getElementById("login-screen");
    const panelScreen = document.getElementById("panel-screen");
    const loginForm = document.getElementById("login-form");
    const loginError = document.getElementById("login-error");
    const login2faWrap = document.getElementById("login-2fa-wrap");
    const login2faCode = document.getElementById("login-2fa-code");
    const tabs = document.getElementById("tabs");
    const tabPlaceholder = document.getElementById("tab-placeholder");
    const toastWrap = document.getElementById("toast-wrap");

    const dashboardView = document.getElementById("dashboard-view");
    const dashboardSpinner = document.getElementById("dashboard-spinner");
    const dashboardError = document.getElementById("dashboard-error");
    const dashboardCards = document.getElementById("dashboard-cards");
    const dashboardHealth = document.getElementById("dashboard-health");
    const dashboardFsm = document.getElementById("dashboard-fsm");
    const dashboardGeneratedAt = document.getElementById("dashboard-generated-at");

    const campaignsView = document.getElementById("campaigns-view");
    const campaignsSpinner = document.getElementById("campaigns-spinner");
    const campaignsError = document.getElementById("campaigns-error");
    const campaignsWorkerState = document.getElementById("campaigns-worker-state");
    const runWorkerBtn = document.getElementById("run-worker-btn");
    const campaignRunResult = document.getElementById("campaign-run-result");
    const campaignGoalSlider = document.getElementById("campaign-goal-slider");
    const campaignGoalInput = document.getElementById("campaign-goal-input");
    const campaignProgressFill = document.getElementById("campaign-progress-fill");
    const campaignProgressText = document.getElementById("campaign-progress-text");
    const speedButtons = Array.from(document.querySelectorAll(".speed-btn"));
    const speedCurrent = document.getElementById("speed-current");
    const campaignActivityLog = document.getElementById("campaign-activity-log");
    const clearActivityLogBtn = document.getElementById("clear-activity-log-btn");
    const templatesView = document.getElementById("templates-view");
    const templateCampaignType = document.getElementById("template-campaign-type");
    const templateTestName = document.getElementById("template-test-name");
    const templateTestVehicle = document.getElementById("template-test-vehicle");
    const templateTestBranch = document.getElementById("template-test-branch");
    const templateTestNotes = document.getElementById("template-test-notes");
    const templateEditor = document.getElementById("template-editor");
    const templateVariableChips = document.getElementById("template-variable-chips");
    const templateSnippets = document.getElementById("template-snippets");
    const templatePreviewBtn = document.getElementById("template-preview-btn");
    const templateVariantsBtn = document.getElementById("template-variants-btn");
    const templateCopyRawBtn = document.getElementById("template-copy-raw-btn");
    const templateCopyPreviewBtn = document.getElementById("template-copy-preview-btn");
    const templateQualityDot = document.getElementById("template-quality-dot");
    const templateQualityLabel = document.getElementById("template-quality-label");
    const templateChecksList = document.getElementById("template-checks-list");
    const templateCharCount = document.getElementById("template-char-count");
    const templateStatsBar = document.getElementById("template-stats-bar");
    const templateInjectBanner = document.getElementById("template-inject-banner");
    const templateBubbles = document.getElementById("template-bubbles");
    const conversationsView = document.getElementById("conversations-view");
    const convLeadIdInput = document.getElementById("conv-lead-id-input");
    const convSearchBtn = document.getElementById("conv-search-btn");
    const convSearchMsg = document.getElementById("conv-search-msg");
    const convSummaryCard = document.getElementById("conv-summary-card");
    const convHeaderRow = document.getElementById("conv-header-row");
    const convStatsGrid = document.getElementById("conv-stats-grid");
    const convControlBtn = document.getElementById("conv-control-btn");
    const convEventsScroll = document.getElementById("conv-events-scroll");
    const csvgenView = document.getElementById("csvgen-view");
    const csvgenDrop = document.getElementById("csvgen-drop");
    const csvgenFileInput = document.getElementById("csvgen-file-input");
    const csvgenFileInfo = document.getElementById("csvgen-file-info");
    const csvgenTableWrap = document.getElementById("csvgen-table-wrap");
    const csvgenTableHead = document.getElementById("csvgen-table-head");
    const csvgenTableBody = document.getElementById("csvgen-table-body");
    const csvgenColumnsChips = document.getElementById("csvgen-columns-chips");
    const csvgenGenerateBtn = document.getElementById("csvgen-generate-btn");
    const csvgenDownloadBtn = document.getElementById("csvgen-download-btn");
    const csvgenResetBtn = document.getElementById("csvgen-reset-btn");
    const csvgenError = document.getElementById("csvgen-error");
    const csvgenPreviewSection = document.getElementById("csvgen-preview-section");
    const csvgenPreviewList = document.getElementById("csvgen-preview-list");
    const monitorView = document.getElementById("monitor-view");
    const monitorSpinner = document.getElementById("monitor-spinner");
    const monitorError = document.getElementById("monitor-error");
    const monitorKpiGrid = document.getElementById("monitor-kpi-grid");
    const monitorStateList = document.getElementById("monitor-state-list");
    const monitorResponseGauge = document.getElementById("monitor-response-gauge");
    const monitorSystemGaugeFg = document.getElementById("monitor-system-gauge-fg");
    const monitorSystemScore = document.getElementById("monitor-system-score");
    const monitorSystemLabel = document.getElementById("monitor-system-label");
    const monitorUsageCrmFill = document.getElementById("monitor-usage-crm-fill");
    const monitorUsageCrmLabel = document.getElementById("monitor-usage-crm-label");
    const monitorUsageDlqFill = document.getElementById("monitor-usage-dlq-fill");
    const monitorUsageDlqLabel = document.getElementById("monitor-usage-dlq-label");
    const monitorAlertsList = document.getElementById("monitor-alerts-list");
    const monitorFunnelList = document.getElementById("monitor-funnel-list");
    const monitorConvRates = document.getElementById("monitor-conv-rates");
    const monitorFooter = document.getElementById("monitor-footer");
    const knowledgeView = document.getElementById("knowledge-view");
    const knowledgeSpinner = document.getElementById("knowledge-spinner");
    const knowledgeUploadForm = document.getElementById("knowledge-upload-form");
    const knowledgeSourceLabel = document.getElementById("knowledge-source-label");
    const knowledgeFileInput = document.getElementById("knowledge-file-input");
    const knowledgeStatus = document.getElementById("knowledge-status");
    const knowledgeSourcesList = document.getElementById("knowledge-sources-list");
    const securityView = document.getElementById("security-view");
    const security2faStatus = document.getElementById("security-2fa-status");
    const security2faSetupBtn = document.getElementById("security-2fa-setup-btn");
    const security2faSetupWrap = document.getElementById("security-2fa-setup-wrap");
    const security2faQr = document.getElementById("security-2fa-qr");
    const security2faSecret = document.getElementById("security-2fa-secret");
    const security2faCode = document.getElementById("security-2fa-code");
    const security2faConfirmBtn = document.getElementById("security-2fa-confirm-btn");
    const auditLogView = document.getElementById("audit-log-view");
    const auditActionFilter = document.getElementById("audit-action-filter");
    const auditFilterBtn = document.getElementById("audit-filter-btn");
    const auditClearBtn = document.getElementById("audit-clear-btn");
    const auditLogBody = document.getElementById("audit-log-body");
    const auditPrevBtn = document.getElementById("audit-prev-btn");
    const auditNextBtn = document.getElementById("audit-next-btn");
    const auditPageLabel = document.getElementById("audit-page-label");
    const navClock = document.getElementById("nav-clock");
    const brandLogo = document.getElementById("brand-logo");
    const brandSupportPhone = document.getElementById("brand-support-phone");
    const brandNameNodes = Array.from(document.querySelectorAll(".brand-name"));
    const brandAdminTitleNodes = Array.from(document.querySelectorAll(".brand-admin-title"));

    let currentTab = "dashboard";
    let dashboardRefreshTimer = null;
    let campaignsRefreshTimer = null;
    let campaignGoal = Number(localStorage.getItem(CAMPAIGN_GOAL_KEY) || 100);
    let latestMessagesSentToday = 0;
    const campaignActivityEntries = [];
    let templateDebounceTimer = null;
    let templateLastPreviewTexts = [];
    let currentTraceLeadId = null;
    let currentTraceData = null;
    let monitorRefreshTimer = null;
    let knowledgeLoading = false;
    let csvgenSelectedFile = null;
    let csvgenDetectedColumns = null;
    let csvgenGeneratedBlob = null;
    let brandConfig = { ...BRAND_DEFAULTS };
    let pendingPreAuthToken = null;
    let auditOffset = 0;
    const auditLimit = 50;

    const templateCampaignExamples = {
      lost: `[Hola|Buenas|Qué tal] {nombre}, [te escribo|te contacto] de {company_name}.
[Hace un tiempo|Recuerdo que] preguntaste por el {vehiculo}.
¿[Sigues interesado|Todavía lo consideras|Ya resolviste]?`,
      quoted: `[Hola|Buenas] {nombre}, soy {bot_name} de {company_name}.
¿[Te pudieron ayudar|Quedaste bien atendido|Te dieron respuesta]
con lo del {vehiculo}?`,
      post_visit: `[Hola|Qué tal] {nombre}, soy {bot_name} de {company_name}.
¿[Qué tal te pareció|Cómo te fue con|Qué impresión te llevaste del]
{vehiculo} [cuando viniste|en tu visita]?`,
      service: `[Hola|Buenas] {nombre}, [te contacto|me comunico] de {company_name}.
¿[Cómo te han atendido|Qué tal la atención|Cómo va todo]
con [tu unidad|el {vehiculo}]?`,
    };

    const templateVariables = [
      "{nombre}",
      "{vehiculo}",
      "{bot_name}",
      "{company_name}",
      "{sucursal}",
      "{notas}",
    ];

    const templateSnippetGroups = [
      {
        title: "Saludos",
        items: [
          "[Hola|Buenas|Qué tal] {nombre}",
          "[Hola|Buenos días] {nombre}, ¿cómo estás?",
        ],
      },
      {
        title: "Intros",
        items: [
          ", soy {bot_name} de {company_name}.",
          ", [te escribo|te contacto] de {company_name}.",
        ],
      },
      {
        title: "Cuerpo",
        items: [
          "\\n[Recuerdo que|Hace un tiempo] preguntaste por el {vehiculo}.",
          "\\n[Quería darte seguimiento|Paso a saludarte] con lo del {vehiculo}.",
        ],
      },
      {
        title: "Cierres",
        items: [
          "\\n¿[Sigues interesado|Todavía lo consideras|Ya resolviste algo]?",
          "\\n¿[Cómo quedaste|Qué tal te fue|Cómo te fue] con eso?",
        ],
      },
    ];

    function showToast(type, message) {
      const toast = document.createElement("div");
      toast.className = `toast ${type}`;
      toast.setAttribute("role", "status");
      toast.style.cursor = "pointer";
      toast.title = "Click para cerrar";
      toast.textContent = message;
      toastWrap.appendChild(toast);
      const dismiss = () => {
        toast.style.transition = "opacity 0.2s ease, transform 0.2s ease";
        toast.style.opacity = "0";
        toast.style.transform = "translateX(10px)";
        setTimeout(() => toast.remove(), 220);
      };
      toast.addEventListener("click", dismiss);
      setTimeout(dismiss, 4000);
    }

    function getToken() {
      return localStorage.getItem(TOKEN_KEY);
    }

    function setToken(token) {
      localStorage.setItem(TOKEN_KEY, token);
    }

    function clearToken() {
      localStorage.removeItem(TOKEN_KEY);
    }

    function showLogin() {
      pendingPreAuthToken = null;
      login2faWrap.classList.add("hidden");
      login2faCode.value = "";
      panelScreen.classList.add("hidden");
      loginScreen.classList.remove("hidden");
    }

    function showPanel() {
      loginScreen.classList.add("hidden");
      panelScreen.classList.remove("hidden");
    }

    function autoLogout() {
      clearToken();
      stopDashboardRefresh();
      stopCampaignsRefresh();
      stopMonitorRefresh();
      showLogin();
      showToast("info", "Sesión expirada. Inicia sesión nuevamente.");
    }

    async function apiFetch(url, options = {}) {
      const token = getToken();
      const headers = new Headers(options.headers || {});
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }
      const response = await fetch(url, { ...options, headers });
      if (response.status === 401) {
        autoLogout();
        throw new Error("unauthorized");
      }
      return response;
    }

    function applyBrandConfig(brand) {
      brandConfig = { ...BRAND_DEFAULTS, ...(brand || {}) };

      for (const node of brandNameNodes) {
        node.textContent = brandConfig.name || BRAND_DEFAULTS.name;
      }
      for (const node of brandAdminTitleNodes) {
        node.textContent = brandConfig.admin_title || BRAND_DEFAULTS.admin_title;
      }
      document.title = brandConfig.admin_title || brandConfig.name || "Panel Admin";

      document.documentElement.style.setProperty("--brand-primary", brandConfig.primary_color || BRAND_DEFAULTS.primary_color);
      document.documentElement.style.setProperty("--brand-accent", brandConfig.accent_color || BRAND_DEFAULTS.accent_color);
      document.documentElement.style.setProperty("--accent", brandConfig.accent_color || BRAND_DEFAULTS.accent_color);

      if (brandLogo) {
        if (brandConfig.logo_url) {
          brandLogo.src = brandConfig.logo_url;
          brandLogo.classList.remove("hidden");
        } else {
          brandLogo.classList.add("hidden");
          brandLogo.removeAttribute("src");
        }
      }

      if (brandSupportPhone) {
        if (brandConfig.support_phone) {
          brandSupportPhone.textContent = `Soporte: ${brandConfig.support_phone}`;
          brandSupportPhone.classList.remove("hidden");
        } else {
          brandSupportPhone.textContent = "";
          brandSupportPhone.classList.add("hidden");
        }
      }
    }

    async function loadBrandConfig() {
      try {
        const response = await apiFetch("/brand/config", { method: "GET" });
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        const brand = await response.json();
        applyBrandConfig(brand);
      } catch (error) {
        applyBrandConfig(BRAND_DEFAULTS);
      }
    }

    function setDashboardLoading(isLoading) {
      dashboardSpinner.classList.toggle("hidden", !isLoading);
      if (isLoading && dashboardCards.children.length === 0) {
        dashboardCards.innerHTML = Array.from({ length: 8 }, () => `
          <article class="metric-card skeleton">
            <div class="metric-label">Loading</div>
            <div class="metric-value">---</div>
          </article>
        `).join("");
      }
    }

    function setCampaignsLoading(isLoading) {
      campaignsSpinner.classList.toggle("hidden", !isLoading);
    }

    function fmtNum(n) {
      const v = Number(n ?? 0);
      return Number.isFinite(v) ? v.toLocaleString("es-MX") : "—";
    }

    function renderMetricCards(stats) {
      const avgResponse = stats.avg_response_time_minutes;
      const cards = [
        { label: "Sesiones activas", value: fmtNum(stats.active_sessions), danger: false, cls: "kpi-cyan" },
        { label: "En handoff", value: fmtNum(stats.sessions_in_handoff), danger: false, cls: "kpi-yellow" },
        { label: "Leads nuevos hoy", value: fmtNum(stats.new_leads_today), danger: false, cls: "kpi-green" },
        { label: "Mensajes enviados hoy", value: fmtNum(stats.messages_sent_today), danger: false, cls: "kpi-cyan" },
        { label: "CRM pendiente", value: fmtNum(stats.crm_sync_pending), danger: false, cls: "kpi-yellow" },
        { label: "CRM con error (DLQ)", value: fmtNum(stats.crm_sync_dlq), danger: Number(stats.crm_sync_dlq ?? 0) > 0, cls: "kpi-red" },
        { label: "Handoffs hoy", value: fmtNum(stats.handoffs_today), danger: false, cls: "kpi-purple" },
        {
          label: "Tiempo resp. promedio",
          value: (avgResponse === null || avgResponse === undefined) ? "N/A" : `${Number(avgResponse).toLocaleString("es-MX")} min`,
          danger: false,
          cls: "kpi-green",
        },
      ];

      dashboardCards.innerHTML = cards
        .map((card) => {
          const alertClass = card.danger ? " dlq-alert" : "";
          const colorClass = card.cls ? ` ${card.cls}` : "";
          return `
            <article class="metric-card${alertClass}${colorClass}">
              <div class="metric-label">${card.label}</div>
              <div class="metric-value">${card.value}</div>
            </article>
          `;
        })
        .join("");
    }

    function renderHealth(stats) {
      const dlq = Number(stats.crm_sync_dlq ?? 0);
      const pending = Number(stats.crm_sync_pending ?? 0);
      const avg = Number(stats.avg_response_time_minutes ?? 0);

      let status = "green";
      let title = "Salud estable";
      let description = "Sin errores en CRM y la cola pendiente está bajo control.";

      if (dlq > 0) {
        status = "red";
        title = "Atención crítica";
        description = "Hay elementos en DLQ. Revisar fallos de sincronización CRM de inmediato.";
      } else if (pending >= 10 || avg > 5) {
        status = "yellow";
        title = "Atención preventiva";
        description = "Sin DLQ, pero hay saturación en CRM pendiente o tiempos de respuesta elevados.";
      }

      dashboardHealth.innerHTML = `
        <span class="health-dot ${status}" aria-hidden="true"></span>
        <div>
          <div><strong>${title}</strong></div>
          <div class="health-desc">${description}</div>
        </div>
      `;
    }

    function renderFsm(stats) {
      const byState = stats.sessions_by_fsm_state && typeof stats.sessions_by_fsm_state === "object"
        ? stats.sessions_by_fsm_state
        : {};
      const entries = Object.entries(byState);
      if (entries.length === 0) {
        dashboardFsm.innerHTML = `
          <h3 class="fsm-title">Estado por FSM</h3>
          <div class="conv-empty-hint">Sin datos disponibles.</div>
        `;
        return;
      }

      const fsmBarColor = {
        idle: "#6b7280",
        greeting: "#3b82f6",
        qualification: "#00d4ff",
        handoff_pending: "#ffab00",
        handoff_active: "#f97316",
        closed: "#22c55e",
      };
      const fsmLabel = {
        idle: "Inactivo",
        greeting: "Saludo",
        qualification: "Calificación",
        handoff_pending: "Handoff pendiente",
        handoff_active: "Handoff activo",
        closed: "Cerrado",
      };
      const maxValue = Math.max(...entries.map(([, value]) => Number(value) || 0), 1);
      const bars = entries
        .sort((a, b) => Number(b[1]) - Number(a[1]))
        .map(([state, value]) => {
          const numericValue = Number(value) || 0;
          const width = Math.max((numericValue / maxValue) * 100, numericValue > 0 ? 2 : 0);
          const color = fsmBarColor[state] || "#94a3b8";
          const label = fsmLabel[state] || state;
          return `
            <div class="fsm-item">
              <div class="fsm-row">
                <span>${label}</span>
                <strong class="tnum">${fmtNum(numericValue)}</strong>
              </div>
              <div class="fsm-bar-bg">
                <div class="fsm-bar-fill" style="width:${width}%;background:${color};"></div>
              </div>
            </div>
          `;
        })
        .join("");

      dashboardFsm.innerHTML = `
        <h3 class="fsm-title">Estado por FSM</h3>
        ${bars}
      `;
    }

    function renderGeneratedAt(stats) {
      if (stats.generated_at) {
        const d = new Date(stats.generated_at);
        const ts = Number.isNaN(d.getTime()) ? stats.generated_at : formatDateTime(stats.generated_at);
        dashboardGeneratedAt.textContent = `Actualizado: ${ts}`;
      } else {
        dashboardGeneratedAt.textContent = "";
      }
    }

    function getTemplateVars() {
      return {
        nombre: templateTestName.value || "Carlos Mendoza",
        vehiculo: templateTestVehicle.value || "Freightliner Cascadia 2020",
        bot_name: TEMPLATE_DEFAULT_BOT_NAME,
        company_name: brandConfig.name || BRAND_DEFAULTS.name,
        sucursal: templateTestBranch.value || "Querétaro",
        notas: templateTestNotes.value || "",
      };
    }

    function resolveSpintax(text) {
      let output = text;
      const blockRegex = /\[([^\[\]]+)\]/g;
      let safety = 0;
      while (blockRegex.test(output) && safety < 1000) {
        safety += 1;
        output = output.replace(blockRegex, (match, content) => {
          const options = content.split("|");
          if (options.length === 0) {
            return match;
          }
          const index = Math.floor(Math.random() * options.length);
          return options[index];
        });
      }
      return output;
    }

    function replaceVars(text) {
      const vars = getTemplateVars();
      return text.replace(/\{(nombre|vehiculo|bot_name|company_name|sucursal|notas)\}/g, (_, key) => {
        return vars[key] ?? "";
      });
    }

    function hasPresentation(text) {
      return /\{bot_name\}/i.test(text) || /ra[uú]l/i.test(text) || /\bsoy\b/i.test(text);
    }

    function injectIntro(text) {
      return `Hola, soy ${TEMPLATE_DEFAULT_BOT_NAME} de {company_name}.\\n${text}`;
    }

    function validateTemplate(text) {
      const errors = [];
      const openBrackets = (text.match(/\[/g) || []).length;
      const closeBrackets = (text.match(/\]/g) || []).length;
      if (openBrackets !== closeBrackets) {
        errors.push("Corchetes desbalanceados.");
      }

      const blocks = text.match(/\[[^\[\]]*\]/g) || [];
      for (const block of blocks) {
        if (!block.includes("|")) {
          errors.push(`Bloque sin separador |: ${block}`);
          break;
        }
      }

      return errors;
    }

    function countCombinations(text) {
      const blocks = text.match(/\[[^\[\]]+\]/g) || [];
      if (blocks.length === 0) {
        return 1;
      }
      return blocks.reduce((acc, block) => {
        const options = block.slice(1, -1).split("|").filter((part) => part.length > 0).length || 1;
        return acc * options;
      }, 1);
    }

    function analyzeQuality(template, resolved) {
      const syntaxErrors = validateTemplate(template);
      const hasQuestion = resolved.includes("?");
      const hasPersonalization = /\{nombre\}|\{vehiculo\}/i.test(template);
      const shortEnough = resolved.length < 250;
      const blocks = template.match(/\[[^\[\]]+\]/g) || [];
      const hasThreeOptions = blocks.some((block) => block.slice(1, -1).split("|").length >= 3);
      const hasSpamWords = /\b(precio|oferta|descuento|promoción|promocion|gratis)\b/i.test(resolved);
      const syntaxOk = syntaxErrors.length === 0;

      const checks = [
        { ok: hasQuestion, label: "Tiene pregunta (?)" },
        { ok: hasPersonalization, label: "Usa {nombre} o {vehiculo}" },
        { ok: shortEnough, label: "Longitud < 250 chars" },
        { ok: hasThreeOptions, label: "Spintax con 3+ opciones por bloque" },
        { ok: !hasSpamWords, label: "Sin palabras spam" },
        { ok: syntaxOk, label: "Sintaxis correcta" },
      ];

      const score = checks.filter((check) => check.ok).length;
      let level = "green";
      let label = "Calidad Alta";
      if (score <= 3) {
        level = "red";
        label = "Calidad Baja";
      } else if (score <= 5) {
        level = "yellow";
        label = "Calidad Media";
      }

      const normalized = resolved.trim();
      const words = normalized ? normalized.split(/\s+/).filter(Boolean).length : 0;
      const lines = normalized ? normalized.split(/\n/).length : 1;
      const variants = countCombinations(template);

      return {
        level,
        label,
        checks,
        stats: {
          chars: resolved.length,
          words,
          lines,
          variants,
        },
        syntaxErrors,
      };
    }

    function insertAtCursor(textToInsert) {
      const start = templateEditor.selectionStart ?? templateEditor.value.length;
      const end = templateEditor.selectionEnd ?? templateEditor.value.length;
      const current = templateEditor.value;
      templateEditor.value = `${current.slice(0, start)}${textToInsert}${current.slice(end)}`;
      const newPos = start + textToInsert.length;
      templateEditor.focus();
      templateEditor.setSelectionRange(newPos, newPos);
      runTemplateLiveAnalysis();
    }

    function applyTemplateType(type) {
      templateEditor.value = templateCampaignExamples[type] || templateCampaignExamples.lost;
      runTemplateLiveAnalysis();
    }

    function updateTemplateQualityUI(analysis) {
      templateQualityDot.classList.remove("green", "yellow", "red");
      templateQualityDot.classList.add(analysis.level);
      templateQualityLabel.textContent = analysis.label;

      const checksHtml = analysis.checks
        .map((check) => `<li>
          <span class="check-sym ${check.ok ? "ok" : "fail"}">${check.ok ? "✓" : "✗"}</span>
          <span>${check.label}</span>
        </li>`)
        .join("");
      const syntaxHtml = analysis.syntaxErrors.length > 0
        ? `<div class="template-syntax-errors">${analysis.syntaxErrors.map((e) =>
            `<div class="syntax-error-item">${escapeHtml(e)}</div>`).join("")}</div>`
        : "";
      templateChecksList.innerHTML = checksHtml + syntaxHtml;

      const chars = analysis.stats.chars;
      const charsCls = chars > 250 ? "danger" : chars > 200 ? "warn" : "";
      const wordsCls = analysis.stats.words > 60 ? "danger" : analysis.stats.words > 40 ? "warn" : "";
      templateCharCount.className = `template-char-count${charsCls ? " " + charsCls : ""}`;
      templateCharCount.textContent = `${chars} / 250 chars`;

      templateStatsBar.innerHTML = `
        <div class="stat-chip"><div class="stat-chip-label">Caracteres</div><div class="stat-chip-value ${charsCls}">${chars}</div></div>
        <div class="stat-chip"><div class="stat-chip-label">Palabras</div><div class="stat-chip-value ${wordsCls}">${analysis.stats.words}</div></div>
        <div class="stat-chip"><div class="stat-chip-label">Líneas</div><div class="stat-chip-value">${analysis.stats.lines}</div></div>
        <div class="stat-chip"><div class="stat-chip-label">Variantes</div><div class="stat-chip-value">${analysis.stats.variants}</div></div>
      `;
    }

    function runTemplateLiveAnalysis() {
      const raw = templateEditor.value || "";
      const needsInjection = !hasPresentation(raw);
      templateInjectBanner.classList.toggle("hidden", !needsInjection);
      const resolved = replaceVars(resolveSpintax(raw));
      const analysis = analyzeQuality(raw, resolved);
      updateTemplateQualityUI(analysis);
    }

    function escapeHtml(text) {
      return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    function buildResolvedTemplateMessage(raw) {
      const needsInjection = !hasPresentation(raw);
      const resolvedBody = replaceVars(resolveSpintax(raw));
      if (!needsInjection) {
        return { fullMessage: resolvedBody, needsInjection };
      }
      const injectedTemplate = injectIntro("{body}");
      const merged = injectedTemplate.replace("{body}", resolvedBody);
      return { fullMessage: replaceVars(merged).trim(), needsInjection };
    }

    function renderBubble(msg, num, wasInjected) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mm = String(now.getMinutes()).padStart(2, "0");

      let renderedMessage = escapeHtml(msg).replace(/\n/g, "<br />");
      if (wasInjected) {
        const [intro, ...rest] = msg.split("\n");
        const restText = rest.join("\n");
        const introHtml = `<span class="wa-injected">${escapeHtml(intro)}</span>`;
        const restHtml = restText ? `<br />${escapeHtml(restText).replace(/\n/g, "<br />")}` : "";
        renderedMessage = `${introHtml}${restHtml}`;
      }

      return `
        <article class="wa-bubble">
          <span class="wa-variant">Variante #${num}</span>
          <div class="wa-message">${renderedMessage}</div>
          <span class="wa-time">${hh}:${mm}</span>
        </article>
      `;
    }

    function generateTemplatePreview(variants) {
      const raw = templateEditor.value || "";
      const bubbleCount = Math.max(1, variants);
      const rendered = [];
      const plainMessages = [];
      for (let i = 0; i < bubbleCount; i += 1) {
        const result = buildResolvedTemplateMessage(raw);
        plainMessages.push(result.fullMessage);
        rendered.push(renderBubble(result.fullMessage, i + 1, result.needsInjection));
      }
      templateLastPreviewTexts = plainMessages;
      templateBubbles.innerHTML = rendered.join("");
      runTemplateLiveAnalysis();
    }

    function debounceTemplateAnalysis() {
      if (templateDebounceTimer !== null) {
        clearTimeout(templateDebounceTimer);
      }
      templateDebounceTimer = setTimeout(() => {
        runTemplateLiveAnalysis();
      }, TEMPLATE_DEBOUNCE_MS);
    }

    function renderTemplateChipsAndSnippets() {
      templateVariableChips.innerHTML = templateVariables
        .map((token) => `<button class="chip" data-insert="${token}" type="button">${token}</button>`)
        .join("");

      templateSnippets.innerHTML = templateSnippetGroups
        .map((group) => {
          const buttons = group.items
            .map((item) => `<button class="snippet-item" data-insert="${item.replace(/"/g, "&quot;")}" type="button">${item}</button>`)
            .join("");
          return `
            <section class="snippet-group">
              <div class="snippet-title">${group.title}</div>
              ${buttons}
            </section>
          `;
        })
        .join("");
    }

    function formatTimestampToHourMinute(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return "--:--";
      }
      return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
    }

    function formatDateTime(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) {
        return "N/A";
      }
      const dd = String(date.getDate()).padStart(2, "0");
      const mm = String(date.getMonth() + 1).padStart(2, "0");
      const yyyy = String(date.getFullYear());
      const hh = String(date.getHours()).padStart(2, "0");
      const min = String(date.getMinutes()).padStart(2, "0");
      return `${dd}/${mm}/${yyyy} ${hh}:${min}`;
    }

    function fsmBadgeClass(state) {
      if (state === "idle") return "fsm-idle";
      if (state === "greeting") return "fsm-greeting";
      if (state === "qualification") return "fsm-qualification";
      if (state === "handoff_pending") return "fsm-handoff_pending";
      if (state === "handoff_active") return "fsm-handoff_active";
      if (state === "closed") return "fsm-closed";
      return "fsm-default";
    }

    function setConvEmptyState(title = "Sin conversación cargada", hint = "Ingresa un Lead ID arriba y presiona Buscar.") {
      convEventsScroll.innerHTML = `
        <div class="conv-empty-state">
          <div class="conv-empty-icon">◎</div>
          <div class="conv-empty-title">${title}</div>
          <div class="conv-empty-hint">${hint}</div>
        </div>`;
    }

    function setConvSearchMessage(message, isError = false) {
      convSearchMsg.textContent = message;
      convSearchMsg.classList.toggle("error", isError);
    }

    function setConvSearchLoading(isLoading) {
      if (isLoading) {
        convSearchBtn.disabled = true;
        convSearchBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>Buscando...</span>';
      } else {
        convSearchBtn.disabled = false;
        convSearchBtn.textContent = "Buscar";
      }
    }

    function setConvControlLoading(isLoading, isTakeControl) {
      if (isLoading) {
        convControlBtn.disabled = true;
        convControlBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>Procesando...</span>';
      } else {
        convControlBtn.disabled = false;
        convControlBtn.textContent = isTakeControl ? "⊕ Tomar Control" : "⊖ Liberar Control";
      }
    }

    function renderTraceSummary(trace) {
      convSummaryCard.classList.remove("hidden");
      const controlBadge = trace.human_in_control
        ? '<span class="control-badge control-agent">Agente activo</span>'
        : '<span class="control-badge control-bot">Bot activo</span>';

      const convFsmLabel = { idle:"Inactivo", greeting:"Saludo", qualification:"Calificación",
        handoff_pending:"Handoff pendiente", handoff_active:"Handoff activo", closed:"Cerrado" };
      const fsmStateLabel = convFsmLabel[trace.current_fsm_state] || trace.current_fsm_state || "N/A";

      convHeaderRow.innerHTML = `
        <div class="conv-header-item col-phone">Teléfono<div class="conv-header-value">${escapeHtml(trace.phone || "N/A")}</div></div>
        <div class="conv-header-item col-state">Estado FSM<div class="conv-header-value"><span class="fsm-badge ${fsmBadgeClass(trace.current_fsm_state)}">${fsmStateLabel}</span></div></div>
        <div class="conv-header-item col-control">Control<div class="conv-header-value">${controlBadge}</div></div>
        <div class="conv-header-item col-date">Creado<div class="conv-header-value">${formatDateTime(trace.created_at)}</div></div>
      `;

      const summary = trace.summary || {};
      convStatsGrid.innerHTML = `
        <div class="conv-mini-stat kpi-cyan"><div class="conv-mini-label">Total mensajes</div><div class="conv-mini-value">${fmtNum(summary.total_messages)}</div></div>
        <div class="conv-mini-stat kpi-green"><div class="conv-mini-label">Inbound</div><div class="conv-mini-value">${fmtNum(summary.inbound_count)}</div></div>
        <div class="conv-mini-stat kpi-yellow"><div class="conv-mini-label">Outbound</div><div class="conv-mini-value">${fmtNum(summary.outbound_count)}</div></div>
        <div class="conv-mini-stat kpi-purple"><div class="conv-mini-label">Duración</div><div class="conv-mini-value">${fmtNum(summary.duration_minutes)} min</div></div>
      `;

      const isTakeControl = !trace.human_in_control;
      convControlBtn.classList.toggle("take", isTakeControl);
      convControlBtn.classList.toggle("release", !isTakeControl);
      setConvControlLoading(false, isTakeControl);
    }

    function renderTraceEvents(trace) {
      const events = Array.isArray(trace.events) ? [...trace.events] : [];
      if (events.length === 0) {
        setConvEmptyState("Conversación sin eventos", "El lead existe pero aún no tiene mensajes registrados.");
        return;
      }

      events.sort((a, b) => {
        const ta = new Date(a.timestamp || 0).getTime();
        const tb = new Date(b.timestamp || 0).getTime();
        return ta - tb;
      });

      convEventsScroll.innerHTML = events
        .map((event) => {
          if (event.type === "inbound") {
            const content = escapeHtml(event.content || "").replace(/\n/g, "<br />");
            return `
              <div class="conv-row inbound">
                <div class="conv-msg inbound">
                  ${content}
                  <span class="conv-time">${formatTimestampToHourMinute(event.timestamp)}</span>
                </div>
              </div>
            `;
          }
          if (event.type === "outbound") {
            const content = escapeHtml(event.content || "").replace(/\n/g, "<br />");
            return `
              <div class="conv-row outbound">
                <div class="conv-msg outbound">
                  ${content}
                  <span class="conv-time">${formatTimestampToHourMinute(event.timestamp)}</span>
                </div>
              </div>
            `;
          }
          if (event.type === "handoff") {
            return '<div class="conv-center-badge handoff">⇄ Handoff</div>';
          }
          if (event.type === "system" || event.type === "fsm_transition") {
            return `<div class="conv-center-badge">FSM: ${escapeHtml(event.fsm_state_before || "-")} → ${escapeHtml(event.fsm_state_after || "-")}</div>`;
          }
          return "";
        })
        .join("");
      convEventsScroll.scrollTop = convEventsScroll.scrollHeight;
    }

    async function loadLeadTrace(leadId) {
      setConvSearchLoading(true);
      setConvSearchMessage("");
      try {
        const response = await apiFetch(`/api/v1/leads/${encodeURIComponent(leadId)}/trace`, { method: "GET" });
        if (response.status === 404) {
          convSummaryCard.classList.add("hidden");
          currentTraceLeadId = null;
          currentTraceData = null;
          setConvEmptyState("Lead no encontrado", `No existe ningún registro para el ID: ${escapeHtml(leadId)}`);
          setConvSearchMessage("Lead no encontrado", true);
          return;
        }
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        const trace = await response.json();
        currentTraceLeadId = leadId;
        currentTraceData = trace;
        renderTraceSummary(trace);
        renderTraceEvents(trace);
        setConvSearchMessage("Lead cargado correctamente");
      } catch (error) {
        convSummaryCard.classList.add("hidden");
        setConvSearchMessage("Error al cargar la conversación", true);
      } finally {
        setConvSearchLoading(false);
      }
    }

    async function executeControlAction() {
      if (!currentTraceLeadId || !currentTraceData) {
        return;
      }
      const isTakeControl = !currentTraceData.human_in_control;
      const endpoint = isTakeControl
        ? `/api/v1/conversations/${encodeURIComponent(currentTraceLeadId)}/take-control`
        : `/api/v1/conversations/${encodeURIComponent(currentTraceLeadId)}/release-control`;
      setConvControlLoading(true, isTakeControl);
      try {
        const response = await apiFetch(endpoint, { method: "POST" });
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        showToast("success", isTakeControl ? "Control tomado" : "Control liberado");
        await loadLeadTrace(currentTraceLeadId);
      } catch (error) {
        showToast("error", "No se pudo cambiar el control");
        setConvControlLoading(false, isTakeControl);
      }
    }

    function csvgenNormalizeHeader(value) {
      return String(value || "").trim().toLowerCase().replace(/[_-]/g, " ");
    }

    function csvgenDetectColumn(headers, aliases) {
      const normalizedAliases = aliases.map(csvgenNormalizeHeader);
      for (const header of headers) {
        if (normalizedAliases.includes(csvgenNormalizeHeader(header))) {
          return header;
        }
      }
      return null;
    }

    function parseCsvRow(line) {
      const result = [];
      let current = "";
      let inQuotes = false;
      for (let i = 0; i < line.length; i += 1) {
        const char = line[i];
        const next = line[i + 1];
        if (char === '"' && inQuotes && next === '"') {
          current += '"';
          i += 1;
          continue;
        }
        if (char === '"') {
          inQuotes = !inQuotes;
          continue;
        }
        if (char === "," && !inQuotes) {
          result.push(current);
          current = "";
          continue;
        }
        current += char;
      }
      result.push(current);
      return result;
    }

    function parseCsvText(text) {
      const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n").filter((line) => line.trim().length > 0);
      if (lines.length === 0) {
        return { headers: [], rows: [] };
      }
      const headers = parseCsvRow(lines[0]).map((item) => item.trim());
      const rows = lines.slice(1).map((line) => {
        const cols = parseCsvRow(line);
        const row = {};
        headers.forEach((header, idx) => {
          row[header] = (cols[idx] ?? "").trim();
        });
        return row;
      });
      return { headers, rows };
    }

    function csvgenSetError(message) {
      csvgenError.textContent = message;
      csvgenError.classList.toggle("hidden", !message);
    }

    function csvgenFormatBytes(size) {
      if (size < 1024) return `${size} B`;
      if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
      return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    function csvgenRenderColumns(headers) {
      const detected = {
        name: csvgenDetectColumn(headers, ["elemento", "nombre", "name", "contacto"]),
        vehicle: csvgenDetectColumn(headers, ["vehiculo", "vehicle", "modelo"]),
        summary: csvgenDetectColumn(headers, ["resumen", "summary", "nota"]),
        template: csvgenDetectColumn(headers, ["template"]) || "Template",
      };
      csvgenDetectedColumns = detected;
      const chips = [
        { label: "Nombre", value: detected.name },
        { label: "Vehículo", value: detected.vehicle },
        { label: "Resumen/Notas", value: detected.summary },
        { label: "Template", value: detected.template },
      ];
      csvgenColumnsChips.innerHTML = chips.map(({ label, value }) => {
        const missing = !value;
        const cls = missing ? "csvgen-chip chip-missing" : "csvgen-chip chip-found";
        const display = value || "No detectado";
        return `<span class="${cls}" title="${missing ? "Columna requerida no encontrada" : value}">${label}: <b>${display}</b></span>`;
      }).join("");
    }

    function csvgenRenderPreviewTable(headers, rows) {
      const previewRows = rows.slice(0, 3);
      csvgenTableHead.innerHTML = `<tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>`;
      csvgenTableBody.innerHTML = previewRows.map((row) => {
        const cols = headers.map((header) => `<td>${escapeHtml(row[header] || "")}</td>`).join("");
        return `<tr>${cols}</tr>`;
      }).join("");
      csvgenTableWrap.classList.toggle("hidden", previewRows.length === 0);
    }

    async function csvgenHandleFile(file) {
      csvgenSetError("");
      csvgenGeneratedBlob = null;
      csvgenDownloadBtn.classList.add("hidden");
      csvgenResetBtn.classList.add("hidden");
      csvgenPreviewSection.classList.add("hidden");
      csvgenPreviewList.innerHTML = "";

      if (!file || !file.name.toLowerCase().endsWith(".csv")) {
        csvgenSetError("Selecciona un archivo CSV válido.");
        return;
      }

      csvgenSelectedFile = file;
      const text = await file.text();
      const parsed = parseCsvText(text);
      csvgenRenderColumns(parsed.headers);
      csvgenRenderPreviewTable(parsed.headers, parsed.rows);
      csvgenFileInfo.innerHTML = `
        <div class="csvgen-file-card">
          <span class="csvgen-file-icon">[ CSV ]</span>
          <span class="csvgen-file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>
          <div class="csvgen-file-badges">
            <span class="csvgen-file-badge">${csvgenFormatBytes(file.size)}</span>
            <span class="csvgen-file-badge">${fmtNum(parsed.rows.length)} contactos</span>
          </div>
        </div>`;
      csvgenFileInfo.classList.remove("hidden");
    }

    function csvgenSetGenerating(isGenerating) {
      if (isGenerating) {
        csvgenGenerateBtn.disabled = true;
        csvgenGenerateBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>Procesando con IA, espera un momento...</span>';
      } else {
        csvgenGenerateBtn.disabled = false;
        csvgenGenerateBtn.textContent = "Generar Templates con IA";
      }
    }

    function csvgenRenderGeneratedPreview(csvText) {
      const parsed = parseCsvText(csvText);
      const templateCol = csvgenDetectColumn(parsed.headers, ["template"]) || "Template";
      const nameCol = csvgenDetectedColumns?.name || csvgenDetectColumn(parsed.headers, ["elemento", "nombre", "name", "contacto"]) || parsed.headers[0];
      const preview = parsed.rows.slice(0, 5);
      csvgenPreviewList.innerHTML = preview.map((row) => `
        <article class="csvgen-preview-card">
          <div class="csvgen-preview-name">${escapeHtml(row[nameCol] || "Sin nombre")}</div>
          <div class="csvgen-preview-template">${escapeHtml(row[templateCol] || "").replace(/\n/g, "<br />")}</div>
        </article>
      `).join("");
      csvgenPreviewSection.classList.remove("hidden");
    }

    async function csvgenGenerateTemplates() {
      if (!csvgenSelectedFile) {
        csvgenSetError("Primero selecciona un archivo CSV.");
        return;
      }
      csvgenSetError("");
      csvgenSetGenerating(true);
      try {
        const formData = new FormData();
        formData.append("file", csvgenSelectedFile);
        const response = await apiFetch("/admin/generate-templates", {
          method: "POST",
          body: formData,
        });
        if (!response.ok) {
          let message = "Error al generar templates";
          try {
            const payload = await response.json();
            if (payload && typeof payload.error === "string") {
              message = payload.error;
            }
          } catch (_) {
            // ignore parsing
          }
          throw new Error(message);
        }
        const blob = await response.blob();
        csvgenGeneratedBlob = blob;
        const text = await blob.text();
        csvgenRenderGeneratedPreview(text);
        csvgenDownloadBtn.classList.remove("hidden");
        csvgenResetBtn.classList.remove("hidden");
      } catch (error) {
        csvgenSetError(error instanceof Error ? error.message : "No se pudo generar templates");
      } finally {
        csvgenSetGenerating(false);
      }
    }

    function csvgenReset() {
      csvgenSelectedFile = null;
      csvgenDetectedColumns = null;
      csvgenGeneratedBlob = null;
      csvgenFileInput.value = "";
      csvgenFileInfo.textContent = "";
      csvgenFileInfo.classList.add("hidden");
      csvgenTableHead.innerHTML = "";
      csvgenTableBody.innerHTML = "";
      csvgenTableWrap.classList.add("hidden");
      csvgenColumnsChips.innerHTML = "";
      csvgenPreviewSection.classList.add("hidden");
      csvgenPreviewList.innerHTML = "";
      csvgenDownloadBtn.classList.add("hidden");
      csvgenResetBtn.classList.add("hidden");
      csvgenSetError("");
    }

    function renderCampaignsWorkerState(stats) {
      const items = [
        { label: "Mensajes en cola", value: fmtNum(stats.messages_pending), cls: "kpi-yellow" },
        { label: "Enviados hoy", value: fmtNum(stats.messages_sent_today), cls: "kpi-cyan" },
        { label: "CRM pendiente", value: fmtNum(stats.crm_sync_pending), cls: Number(stats.crm_sync_pending ?? 0) > 50 ? "kpi-red" : "kpi-green" },
      ];
      campaignsWorkerState.innerHTML = items
        .map((item) => `
          <article class="mini-card ${item.cls}">
            <div class="mini-label">${item.label}</div>
            <div class="mini-value">${item.value}</div>
          </article>
        `)
        .join("");
    }

    function clampGoal(value) {
      const numeric = Number(value);
      if (!Number.isFinite(numeric) || numeric < 1) {
        return 1;
      }
      return Math.min(Math.round(numeric), 2000);
    }

    function syncGoalInputs(goal) {
      campaignGoalSlider.value = String(goal);
      campaignGoalInput.value = String(goal);
    }

    function renderCampaignProgress(messagesSentToday) {
      const sent = Number(messagesSentToday ?? 0);
      const goal = clampGoal(campaignGoal);
      const ratio = sent / goal;
      const percentageRaw = Math.round(ratio * 100);
      const percentage = Math.max(0, Math.min(percentageRaw, 100));
      campaignProgressFill.style.width = `${percentage}%`;
      campaignProgressFill.classList.remove("green", "yellow", "cyan");
      if (percentageRaw >= 100) {
        campaignProgressFill.classList.add("cyan");
      } else if (percentageRaw >= 80) {
        campaignProgressFill.classList.add("yellow");
      } else {
        campaignProgressFill.classList.add("green");
      }
      campaignProgressText.textContent = `${fmtNum(sent)} / ${fmtNum(goal)} mensajes (${percentageRaw}%)`;
    }

    function speedLabel(speed) {
      if (speed === "slow") return "Lento";
      if (speed === "fast") return "Rápido";
      return "Normal";
    }

    function renderSpeedSelection() {
      const current = localStorage.getItem(SPEED_KEY) || "normal";
      for (const btn of speedButtons) {
        btn.classList.toggle("active", btn.dataset.speed === current);
      }
      speedCurrent.textContent = `Velocidad actual: ${speedLabel(current)}`;
    }

    function renderCampaignActivityLog() {
      if (campaignActivityEntries.length === 0) {
        campaignActivityLog.innerHTML = `
          <li class="activity-empty">
            <span style="display:block;margin-bottom:4px;">Sin ejecuciones todavía.</span>
            <span class="conv-empty-hint">Usa "Ejecutar Worker Ahora" para lanzar una campaña.</span>
          </li>`;
        return;
      }
      campaignActivityLog.innerHTML = campaignActivityEntries
        .map((entry) => `<li class="activity-item ${entry.ok ? "log-ok" : "log-fail"}">`
          + `<span class="log-ts">${entry.ts}</span>`
          + `<span class="log-sym ${entry.ok ? "log-ok-sym" : "log-fail-sym"}">${entry.ok ? "✓" : "✗"}</span>`
          + `<span class="log-body">Procesados: <b>${entry.processed}</b> &nbsp;`
          + `Exitosos: <b class="log-ok-sym">${entry.succeeded}</b> &nbsp;`
          + `Fallidos: <b class="${entry.failed > 0 ? "log-fail-sym" : ""}">${entry.failed}</b></span>`
          + `</li>`)
        .join("");
    }

    function appendCampaignActivityLog({ ok, processed, succeeded, failed }) {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mm = String(now.getMinutes()).padStart(2, "0");
      const ss = String(now.getSeconds()).padStart(2, "0");
      campaignActivityEntries.unshift({ ok, processed, succeeded, failed, ts: `${hh}:${mm}:${ss}` });
      if (campaignActivityEntries.length > 20) {
        campaignActivityEntries.length = 20;
      }
      renderCampaignActivityLog();
    }

    function setRunWorkerLoading(isLoading) {
      if (isLoading) {
        runWorkerBtn.disabled = true;
        runWorkerBtn.innerHTML = '<span class="spinner" aria-hidden="true"></span><span>Ejecutando...</span>';
      } else {
        runWorkerBtn.disabled = false;
        runWorkerBtn.textContent = "Ejecutar Worker Ahora";
      }
    }

    function showCampaignRunResult(ok, message) {
      campaignRunResult.classList.remove("hidden", "success", "error");
      campaignRunResult.classList.add(ok ? "success" : "error");
      campaignRunResult.innerHTML = `<span style="font-weight:700;margin-right:6px;">${ok ? "OK" : "ERROR"}</span>${escapeHtml(message)}`;
    }

    async function loadDashboardStats() {
      dashboardError.classList.add("hidden");
      dashboardError.textContent = "";
      setDashboardLoading(true);

      try {
        const response = await apiFetch("/api/v1/dashboard/stats", { method: "GET" });
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        const stats = await response.json();
        renderMetricCards(stats);
        renderHealth(stats);
        renderFsm(stats);
        renderGeneratedAt(stats);
      } catch (error) {
        dashboardError.textContent = "No se pudo cargar el dashboard. Intenta nuevamente.";
        dashboardError.classList.remove("hidden");
      } finally {
        setDashboardLoading(false);
      }
    }

    async function loadCampaignsState() {
      campaignsError.classList.add("hidden");
      campaignsError.textContent = "";
      setCampaignsLoading(true);
      try {
        const response = await apiFetch("/api/v1/dashboard/stats", { method: "GET" });
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        const stats = await response.json();
        latestMessagesSentToday = Number(stats.messages_sent_today ?? 0);
        renderCampaignsWorkerState(stats);
        renderCampaignProgress(latestMessagesSentToday);
      } catch (error) {
        campaignsError.textContent = "No se pudo cargar el estado de campañas.";
        campaignsError.classList.remove("hidden");
      } finally {
        setCampaignsLoading(false);
      }
    }

    async function runCampaignWorkerNow() {
      campaignRunResult.classList.add("hidden");
      setRunWorkerLoading(true);
      try {
        const response = await apiFetch("/api/v1/campaigns/run", { method: "POST" });
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        const payload = await response.json();
        const processed = Number(payload.processed ?? 0);
        const succeeded = Number(payload.succeeded ?? 0);
        const failed = Number(payload.failed ?? 0);
        const durationMs = Number(payload.duration_ms ?? 0);
        showCampaignRunResult(
          true,
          `Procesados: ${fmtNum(processed)} · Exitosos: ${fmtNum(succeeded)} · Fallidos: ${fmtNum(failed)} · ${fmtNum(durationMs)}ms`
        );
        appendCampaignActivityLog({ ok: true, processed, succeeded, failed });
        await loadCampaignsState();
      } catch (error) {
        showCampaignRunResult(false, "Error al ejecutar worker. Intenta nuevamente.");
        appendCampaignActivityLog({ ok: false, processed: 0, succeeded: 0, failed: 0 });
      } finally {
        setRunWorkerLoading(false);
      }
    }

    function monitorStateClass(state) {
      if (state === "idle") return "state-idle";
      if (state === "greeting") return "state-greeting";
      if (state === "qualification") return "state-qualification";
      if (state === "handoff_pending") return "state-handoff_pending";
      if (state === "handoff_active") return "state-handoff_active";
      if (state === "closed") return "state-closed";
      return "state-default";
    }

    function setMonitorLoading(isLoading) {
      monitorSpinner.classList.toggle("hidden", !isLoading);
    }

    function computeSystemScore(stats) {
      const dlq = Number(stats.crm_sync_dlq ?? 0);
      const pending = Number(stats.crm_sync_pending ?? 0);
      const handoff = Number(stats.sessions_in_handoff ?? 0);
      const avg = Number(stats.avg_response_time_minutes ?? 0);
      const raw = 100
        - (dlq * 15)
        - (pending > 50 ? 10 : 0)
        - (handoff > 5 ? 5 : 0)
        - (avg > 5 ? 10 : 0);
      return Math.max(0, Math.min(100, Math.round(raw)));
    }

    function renderMonitorKpis(stats) {
      const dlq = Number(stats.crm_sync_dlq ?? 0);
      const items = [
        { label: "Sesiones activas", value: fmtNum(stats.active_sessions), cls: "kpi-cyan" },
        { label: "En handoff", value: fmtNum(stats.sessions_in_handoff), cls: "kpi-yellow" },
        { label: "Leads nuevos hoy", value: fmtNum(stats.new_leads_today), cls: "kpi-green" },
        { label: "Mensajes pendientes", value: fmtNum(stats.messages_pending), cls: "kpi-yellow" },
        { label: "DLQ errors", value: fmtNum(dlq), cls: dlq > 0 ? "kpi-red" : "kpi-green" },
        { label: "Handoffs hoy", value: fmtNum(stats.handoffs_today), cls: "kpi-purple" },
      ];
      monitorKpiGrid.innerHTML = items.map((item) => `
        <article class="monitor-kpi-card ${item.cls}">
          <div class="monitor-kpi-label">${item.label}</div>
          <div class="monitor-kpi-value">${item.value}</div>
        </article>
      `).join("");
    }

    function renderMonitorStates(stats) {
      const byState = stats.sessions_by_fsm_state && typeof stats.sessions_by_fsm_state === "object"
        ? stats.sessions_by_fsm_state
        : {};
      const entries = Object.entries(byState);
      if (entries.length === 0) {
        monitorStateList.innerHTML = `
          <div class="conv-empty-state" style="padding:20px 10px;">
            <div class="conv-empty-icon">◎</div>
            <div class="conv-empty-title">Sin sesiones activas</div>
          </div>`;
        return;
      }
      const fsmReadable = { idle:"Inactivo", greeting:"Saludo", qualification:"Calificación",
        handoff_pending:"Handoff pendiente", handoff_active:"Handoff activo", closed:"Cerrado" };
      const maxValue = Math.max(...entries.map(([, value]) => Number(value) || 0), 1);
      monitorStateList.innerHTML = entries
        .sort((a, b) => Number(b[1]) - Number(a[1]))
        .map(([state, value]) => {
          const numeric = Number(value) || 0;
          const width = Math.max((numeric / maxValue) * 100, numeric > 0 ? 2 : 0);
          return `
            <div class="state-item">
              <div class="state-head">
                <span>${fsmReadable[state] || state}</span>
                <strong class="tnum">${fmtNum(numeric)}</strong>
              </div>
              <div class="state-bar-bg">
                <div class="state-bar-fill ${monitorStateClass(state)}" style="width:${width}%;"></div>
              </div>
            </div>
          `;
        })
        .join("");
    }

    function renderMonitorResponse(stats) {
      const avg = Number(stats.avg_response_time_minutes ?? 0);
      const bands = `
        <div class="response-gauge-bands">
          <div class="response-band green"></div>
          <div class="response-band yellow"></div>
          <div class="response-band red"></div>
        </div>
        <div class="response-gauge-legend">0–2 min excelente · 2–5 normal · >5 lento</div>`;
      if (!avg) {
        monitorResponseGauge.innerHTML = `<div class="response-level yellow">Sin datos</div><div class="speed-current">Promedio: N/A</div>${bands}`;
        return;
      }
      let level = "green";
      let label = "Excelente";
      let barColor = "var(--success)";
      const maxScale = 10;
      const barWidth = Math.min((avg / maxScale) * 100, 100);
      if (avg > 5) { level = "red"; label = "Lento"; barColor = "var(--danger)"; }
      else if (avg > 2) { level = "yellow"; label = "Normal"; barColor = "var(--warning)"; }
      monitorResponseGauge.innerHTML = `
        <div class="response-level ${level}">${label}</div>
        <div class="response-gauge-bar-track">
          <div class="response-gauge-bar-fill" style="width:${barWidth.toFixed(1)}%;background:${barColor};"></div>
        </div>
        ${bands}
        <div class="speed-current">Promedio: ${avg.toFixed(1)} min</div>
      `;
    }

    function renderMonitorSystemHealth(stats) {
      const score = computeSystemScore(stats);
      const progress = score / 100;
      const offset = MONITOR_GAUGE_CIRCUMFERENCE * (1 - progress);
      let color = "#22c55e";
      let label = "Excelente";
      if (score < 60) {
        color = "#ef4444";
        label = "Crítico";
      } else if (score < 80) {
        color = "#f59e0b";
        label = "Advertencia";
      }
      monitorSystemGaugeFg.style.strokeDasharray = String(MONITOR_GAUGE_CIRCUMFERENCE);
      monitorSystemGaugeFg.style.strokeDashoffset = String(offset);
      monitorSystemGaugeFg.style.stroke = color;
      monitorSystemScore.textContent = String(score);
      monitorSystemLabel.textContent = label;

      const crmPct = Math.min(100, Math.max(0, (Number(stats.crm_sync_pending ?? 0) / 100) * 100));
      const dlqPct = Math.min(100, Math.max(0, (Number(stats.crm_sync_dlq ?? 0) / 10) * 100));
      monitorUsageCrmFill.style.width = `${crmPct}%`;
      monitorUsageDlqFill.style.width = `${dlqPct}%`;
      monitorUsageCrmLabel.textContent = `${Math.round(crmPct)}%`;
      monitorUsageDlqLabel.textContent = `${Math.round(dlqPct)}%`;
      monitorUsageDlqFill.style.background = Number(stats.crm_sync_dlq ?? 0) > 0 ? "#ef4444" : "#334155";

      const alerts = [];
      if (Number(stats.crm_sync_dlq ?? 0) > 0) {
        alerts.push({ level: "error", text: `${stats.crm_sync_dlq} operaciones en DLQ — revisar CRM` });
      }
      if (Number(stats.crm_sync_pending ?? 0) > 50) {
        alerts.push({ level: "warn", text: `Backlog CRM: ${stats.crm_sync_pending} pendientes` });
      }
      if (Number(stats.sessions_in_handoff ?? 0) > 5) {
        alerts.push({ level: "warn", text: `${stats.sessions_in_handoff} handoffs activos simultáneos` });
      }
      if (Number(stats.avg_response_time_minutes ?? 0) > 5) {
        alerts.push({ level: "warn", text: `Tiempo de respuesta elevado: ${Number(stats.avg_response_time_minutes).toFixed(1)} min` });
      }
      if (Number(stats.new_leads_today ?? 0) === 0) {
        alerts.push({ level: "info", text: "Sin leads nuevos hoy" });
      }
      if (alerts.length === 0) {
        alerts.push({ level: "ok", text: "Todos los sistemas operando normalmente" });
      }
      const alertTag = { error: "CRÍTICO", warn: "AVISO", info: "INFO", ok: "OK" };
      monitorAlertsList.innerHTML = alerts.map(({ level, text }) =>
        `<div class="alert-item alert-${level}"><span class="alert-level-tag">${alertTag[level] || level}</span>${escapeHtml(text)}</div>`
      ).join("");
    }

    function renderMonitorFunnel(stats) {
      const byState = stats.sessions_by_fsm_state && typeof stats.sessions_by_fsm_state === "object"
        ? stats.sessions_by_fsm_state
        : {};
      const funnelOrder = ["idle", "greeting", "qualification", "handoff_pending", "handoff_active", "closed"];
      const maxValue = Math.max(...funnelOrder.map((state) => Number(byState[state] ?? 0)), 1);
      const funnelLabel = { idle:"Inactivo", greeting:"Saludo", qualification:"Calificación",
        handoff_pending:"Handoff pendiente", handoff_active:"Handoff activo", closed:"Cerrado" };
      monitorFunnelList.innerHTML = funnelOrder.map((state) => {
        const value = Number(byState[state] ?? 0);
        const width = Math.max((value / maxValue) * 100, value > 0 ? 2 : 0);
        return `
          <div class="funnel-item">
            <div class="funnel-head">
              <span>${funnelLabel[state] || state}</span>
              <strong class="tnum">${fmtNum(value)}</strong>
            </div>
            <div class="funnel-bar-bg"><div class="funnel-bar-fill ${monitorStateClass(state)}" style="width:${width}%;"></div></div>
          </div>
        `;
      }).join("");

      const idle = Number(byState.idle ?? 0);
      const greeting = Number(byState.greeting ?? 0);
      const qualification = Number(byState.qualification ?? 0);
      const handoffActive = Number(byState.handoff_active ?? 0);

      const greetingRate = idle > 0 ? (greeting / idle) * 100 : 0;
      const qualificationRate = greeting > 0 ? (qualification / greeting) * 100 : 0;
      const handoffRate = qualification > 0 ? (handoffActive / qualification) * 100 : 0;
      monitorConvRates.innerHTML = [
        { label: "Greeting rate", rate: greetingRate },
        { label: "Qualification rate", rate: qualificationRate },
        { label: "Handoff rate", rate: handoffRate },
      ].map(({ label, rate }) => {
        const cls = rate >= 50 ? "high" : rate >= 20 ? "mid" : "low";
        return `<div class="conv-rate-item"><span>${label}</span><span class="conv-rate-badge ${cls}">${rate.toFixed(1)}%</span></div>`;
      }).join("");

      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mm = String(now.getMinutes()).padStart(2, "0");
      const ss = String(now.getSeconds()).padStart(2, "0");
      monitorFooter.textContent = `Actualizado: ${hh}:${mm}:${ss} · auto-refresh cada 10s`;
    }

    async function loadMonitorStats() {
      monitorError.classList.add("hidden");
      monitorError.textContent = "";
      setMonitorLoading(true);
      try {
        const response = await apiFetch("/api/v1/dashboard/stats", { method: "GET" });
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        const stats = await response.json();
        renderMonitorKpis(stats);
        renderMonitorStates(stats);
        renderMonitorResponse(stats);
        renderMonitorSystemHealth(stats);
        renderMonitorFunnel(stats);
      } catch (error) {
        monitorError.textContent = "No se pudo cargar monitor.";
        monitorError.classList.remove("hidden");
      } finally {
        setMonitorLoading(false);
      }
    }

    function setKnowledgeLoading(isLoading) {
      knowledgeLoading = isLoading;
      knowledgeSpinner.classList.toggle("hidden", !isLoading);
    }

    function renderKnowledgeSources(sources) {
      if (!Array.isArray(sources) || sources.length === 0) {
        knowledgeSourcesList.innerHTML = `<div class="csvgen-note">No hay fuentes cargadas.</div>`;
        return;
      }

      knowledgeSourcesList.innerHTML = sources.map((source) => {
        const label = escapeHtml(String(source.source_label || "Sin nombre"));
        const chunks = Number(source.chunk_count || 0);
        const indexedAt = source.indexed_at ? escapeHtml(String(source.indexed_at)) : "N/A";
        return `
          <div class="csvgen-preview-item">
            <div><strong>${label}</strong></div>
            <div>Chunks: ${chunks}</div>
            <div>Fecha: ${indexedAt}</div>
            <div style="margin-top:8px;">
              <button class="csvgen-btn" type="button" data-knowledge-delete="${label}">Eliminar</button>
            </div>
          </div>
        `;
      }).join("");
    }

    async function loadKnowledgeSources() {
      setKnowledgeLoading(true);
      try {
        const response = await apiFetch("/api/v1/admin/knowledge/sources", { method: "GET" });
        if (!response.ok) {
          throw new Error(`http_${response.status}`);
        }
        const payload = await response.json();
        renderKnowledgeSources(payload.sources || []);
      } catch (error) {
        knowledgeStatus.textContent = "No se pudo cargar la lista de fuentes.";
      } finally {
        setKnowledgeLoading(false);
      }
    }

    async function uploadKnowledgeFile() {
      if (knowledgeLoading) {
        return;
      }
      const file = knowledgeFileInput.files?.[0];
      const sourceLabel = (knowledgeSourceLabel.value || "").trim();
      if (!file || !sourceLabel) {
        knowledgeStatus.textContent = "Selecciona archivo y nombre de fuente.";
        return;
      }

      setKnowledgeLoading(true);
      knowledgeStatus.textContent = "Subiendo y procesando documento...";
      try {
        const formData = new FormData();
        formData.append("file", file);
        formData.append("source_label", sourceLabel);
        const response = await apiFetch("/api/v1/admin/knowledge/upload", {
          method: "POST",
          body: formData,
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "upload_failed");
        }
        knowledgeStatus.textContent = `Completado: ${payload.chunks_created} chunks para "${sourceLabel}".`;
        knowledgeUploadForm.reset();
        await loadKnowledgeSources();
      } catch (error) {
        knowledgeStatus.textContent = `Error en upload: ${error.message || error}`;
      } finally {
        setKnowledgeLoading(false);
      }
    }

    async function deleteKnowledgeSource(sourceLabel) {
      if (!sourceLabel || knowledgeLoading) {
        return;
      }
      setKnowledgeLoading(true);
      knowledgeStatus.textContent = `Eliminando fuente "${sourceLabel}"...`;
      try {
        const response = await apiFetch(`/api/v1/admin/knowledge/sources/${encodeURIComponent(sourceLabel)}`, {
          method: "DELETE",
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "delete_failed");
        }
        knowledgeStatus.textContent = `Eliminado: ${payload.chunks_deleted} chunks de "${sourceLabel}".`;
        await loadKnowledgeSources();
      } catch (error) {
        knowledgeStatus.textContent = `Error al eliminar: ${error.message || error}`;
      } finally {
        setKnowledgeLoading(false);
      }
    }

    function renderAuditEntries(entries) {
      if (!Array.isArray(entries) || entries.length === 0) {
        auditLogBody.innerHTML = `<tr><td colspan="4" class="csvgen-note">Sin actividad registrada.</td></tr>`;
        return;
      }
      auditLogBody.innerHTML = entries.map((item) => {
        const ts = escapeHtml(String(item.timestamp || "N/A"));
        const action = escapeHtml(String(item.action || "N/A"));
        const resource = `${escapeHtml(String(item.resource_type || "-"))} / ${escapeHtml(String(item.resource_id || "-"))}`;
        const ip = escapeHtml(String(item.ip_address || "-"));
        return `<tr><td>${ts}</td><td>${action}</td><td>${resource}</td><td>${ip}</td></tr>`;
      }).join("");
    }

    async function loadAuditLog() {
      const action = (auditActionFilter.value || "").trim();
      const query = new URLSearchParams({
        limit: String(auditLimit),
        offset: String(auditOffset),
      });
      if (action) {
        query.set("action", action);
      }

      try {
        const response = await apiFetch(`/admin/audit-log?${query.toString()}`, { method: "GET" });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || `http_${response.status}`);
        }
        renderAuditEntries(payload.entries || []);
        const currentPage = Math.floor(auditOffset / auditLimit) + 1;
        auditPageLabel.textContent = `Página ${currentPage}`;
        auditPrevBtn.disabled = auditOffset === 0;
        auditNextBtn.disabled = !Array.isArray(payload.entries) || payload.entries.length < auditLimit;
      } catch (error) {
        renderAuditEntries([]);
        auditPageLabel.textContent = "Error cargando registro";
      }
    }

    async function load2faStatus() {
      try {
        const response = await apiFetch("/api/v1/auth/2fa/status", { method: "GET" });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || `http_${response.status}`);
        }
        security2faStatus.textContent = payload.enabled ? "2FA: Activo ✓" : "2FA: Inactivo";
      } catch (error) {
        security2faStatus.textContent = "2FA: Estado no disponible";
      }
    }

    async function setup2fa() {
      try {
        const response = await apiFetch("/api/v1/auth/2fa/setup", { method: "POST" });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || `http_${response.status}`);
        }
        security2faQr.src = payload.qr_code;
        security2faSecret.textContent = payload.secret || "";
        security2faSetupWrap.classList.remove("hidden");
        showToast("info", "Escanea el QR y confirma con un código.");
      } catch (error) {
        showToast("error", `No se pudo iniciar setup 2FA: ${error.message || error}`);
      }
    }

    async function confirm2fa() {
      const code = (security2faCode.value || "").trim();
      if (!code) {
        showToast("error", "Ingresa el código TOTP.");
        return;
      }
      try {
        const response = await apiFetch("/api/v1/auth/2fa/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code }),
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || `http_${response.status}`);
        }
        showToast("success", "2FA activado correctamente.");
        security2faCode.value = "";
        await load2faStatus();
      } catch (error) {
        showToast("error", `No se pudo activar 2FA: ${error.message || error}`);
      }
    }

    function stopDashboardRefresh() {
      if (dashboardRefreshTimer !== null) {
        clearInterval(dashboardRefreshTimer);
        dashboardRefreshTimer = null;
      }
    }

    function startDashboardRefresh() {
      stopDashboardRefresh();
      dashboardRefreshTimer = setInterval(() => {
        if (currentTab === "dashboard") {
          loadDashboardStats();
        }
      }, DASHBOARD_REFRESH_MS);
    }

    function stopCampaignsRefresh() {
      if (campaignsRefreshTimer !== null) {
        clearInterval(campaignsRefreshTimer);
        campaignsRefreshTimer = null;
      }
    }

    function startCampaignsRefresh() {
      stopCampaignsRefresh();
      campaignsRefreshTimer = setInterval(() => {
        if (currentTab === "campanas") {
          loadCampaignsState();
        }
      }, CAMPAIGNS_REFRESH_MS);
    }

    function stopMonitorRefresh() {
      if (monitorRefreshTimer !== null) {
        clearInterval(monitorRefreshTimer);
        monitorRefreshTimer = null;
      }
    }

    function startMonitorRefresh() {
      stopMonitorRefresh();
      monitorRefreshTimer = setInterval(() => {
        if (currentTab === "monitor") {
          loadMonitorStats();
        }
      }, MONITOR_REFRESH_MS);
    }

    function setCampaignGoal(goal) {
      campaignGoal = clampGoal(goal);
      localStorage.setItem(CAMPAIGN_GOAL_KEY, String(campaignGoal));
      syncGoalInputs(campaignGoal);
      renderCampaignProgress(latestMessagesSentToday);
    }

    function setActiveTab(tabName) {
      currentTab = tabName;
      for (const tab of tabs.querySelectorAll(".tab")) {
        const isActive = tab.dataset.tab === tabName;
        tab.classList.toggle("active", isActive);
        tab.setAttribute("aria-selected", isActive ? "true" : "false");
        tab.setAttribute("tabindex", isActive ? "0" : "-1");
      }
      window.scrollTo({ top: 0, behavior: "instant" });

      if (tabName === "dashboard") {
        stopCampaignsRefresh();
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        campaignsView.classList.add("hidden");
        templatesView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.add("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.add("hidden");
        dashboardView.classList.remove("hidden");
        loadDashboardStats();
        startDashboardRefresh();
        return;
      }

      stopDashboardRefresh();
      if (tabName === "campanas") {
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        templatesView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.add("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.add("hidden");
        campaignsView.classList.remove("hidden");
        loadCampaignsState();
        startCampaignsRefresh();
        return;
      }

      if (tabName === "templates") {
        stopCampaignsRefresh();
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        campaignsView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.add("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.add("hidden");
        templatesView.classList.remove("hidden");
        runTemplateLiveAnalysis();
        if (templateBubbles.children.length === 0) {
          generateTemplatePreview(1);
        }
        setTimeout(() => templateEditor.focus(), 50);
        return;
      }

      if (tabName === "generador_csv") {
        stopCampaignsRefresh();
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        campaignsView.classList.add("hidden");
        templatesView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.add("hidden");
        csvgenView.classList.remove("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.add("hidden");
        return;
      }

      if (tabName === "conversaciones") {
        stopCampaignsRefresh();
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        campaignsView.classList.add("hidden");
        templatesView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        monitorView.classList.add("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.add("hidden");
        conversationsView.classList.remove("hidden");
        if (!currentTraceData) {
          convSummaryCard.classList.add("hidden");
          setConvEmptyState();
        }
        setTimeout(() => convLeadIdInput.focus(), 50);
        return;
      }

      if (tabName === "monitor") {
        stopCampaignsRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        campaignsView.classList.add("hidden");
        templatesView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.remove("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.add("hidden");
        loadMonitorStats();
        startMonitorRefresh();
        return;
      }

      if (tabName === "knowledge") {
        stopCampaignsRefresh();
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        campaignsView.classList.add("hidden");
        templatesView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.add("hidden");
        knowledgeView.classList.remove("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.add("hidden");
        loadKnowledgeSources();
        return;
      }

      if (tabName === "security") {
        stopCampaignsRefresh();
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        campaignsView.classList.add("hidden");
        templatesView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.add("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.remove("hidden");
        auditLogView.classList.add("hidden");
        load2faStatus();
        return;
      }

      if (tabName === "audit_log") {
        stopCampaignsRefresh();
        stopMonitorRefresh();
        tabPlaceholder.classList.add("hidden");
        dashboardView.classList.add("hidden");
        campaignsView.classList.add("hidden");
        templatesView.classList.add("hidden");
        csvgenView.classList.add("hidden");
        conversationsView.classList.add("hidden");
        monitorView.classList.add("hidden");
        knowledgeView.classList.add("hidden");
        securityView.classList.add("hidden");
        auditLogView.classList.remove("hidden");
        loadAuditLog();
        return;
      }

      stopCampaignsRefresh();
      stopMonitorRefresh();
      dashboardView.classList.add("hidden");
      campaignsView.classList.add("hidden");
      templatesView.classList.add("hidden");
      csvgenView.classList.add("hidden");
      conversationsView.classList.add("hidden");
      monitorView.classList.add("hidden");
      knowledgeView.classList.add("hidden");
      securityView.classList.add("hidden");
      auditLogView.classList.add("hidden");
      tabPlaceholder.classList.remove("hidden");
      const activeLabel = tabs.querySelector(`.tab[data-tab="${tabName}"]`)?.textContent || "Sección";
      tabPlaceholder.textContent = `Sección "${activeLabel}" lista para implementar.`;
    }

    runWorkerBtn.addEventListener("click", () => {
      runCampaignWorkerNow();
    });

    campaignGoalSlider.addEventListener("input", () => {
      setCampaignGoal(campaignGoalSlider.value);
    });

    campaignGoalInput.addEventListener("change", () => {
      setCampaignGoal(campaignGoalInput.value);
    });

    for (const btn of speedButtons) {
      btn.addEventListener("click", () => {
        localStorage.setItem(SPEED_KEY, btn.dataset.speed || "normal");
        renderSpeedSelection();
      });
    }

    clearActivityLogBtn.addEventListener("click", () => {
      campaignActivityEntries.length = 0;
      renderCampaignActivityLog();
    });

    templateCampaignType.addEventListener("change", () => {
      applyTemplateType(templateCampaignType.value);
    });

    templateVariableChips.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) {
        return;
      }
      const text = target.dataset.insert;
      if (text) {
        insertAtCursor(text);
      }
    });

    templateSnippets.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) {
        return;
      }
      const text = target.dataset.insert;
      if (text) {
        insertAtCursor(text.replace(/\\n/g, "\n"));
      }
    });

    templateEditor.addEventListener("input", () => {
      debounceTemplateAnalysis();
    });

    for (const el of [templateTestName, templateTestVehicle, templateTestBranch, templateTestNotes]) {
      el.addEventListener("input", () => {
        debounceTemplateAnalysis();
      });
    }

    templatePreviewBtn.addEventListener("click", () => {
      generateTemplatePreview(1);
    });

    templateVariantsBtn.addEventListener("click", () => {
      generateTemplatePreview(5);
    });

    templateCopyRawBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(templateEditor.value || "");
        showToast("success", "Template copiado");
      } catch (error) {
        showToast("error", "No se pudo copiar el template");
      }
    });

    templateCopyPreviewBtn.addEventListener("click", async () => {
      try {
        const text = templateLastPreviewTexts.length > 0
          ? templateLastPreviewTexts.join("\n\n")
          : buildResolvedTemplateMessage(templateEditor.value || "").fullMessage;
        await navigator.clipboard.writeText(text);
        showToast("success", "Preview copiado");
      } catch (error) {
        showToast("error", "No se pudo copiar el preview");
      }
    });

    convSearchBtn.addEventListener("click", () => {
      const leadId = (convLeadIdInput.value || "").trim();
      if (!leadId) {
        setConvSearchMessage("Ingresa un Lead ID", true);
        return;
      }
      loadLeadTrace(leadId);
    });

    convLeadIdInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        convSearchBtn.click();
      }
    });

    convControlBtn.addEventListener("click", () => {
      executeControlAction();
    });

    csvgenDrop.addEventListener("click", () => {
      csvgenFileInput.click();
    });

    csvgenDrop.addEventListener("dragover", (event) => {
      event.preventDefault();
      csvgenDrop.classList.add("dragover");
    });

    csvgenDrop.addEventListener("dragleave", () => {
      csvgenDrop.classList.remove("dragover");
    });

    csvgenDrop.addEventListener("drop", (event) => {
      event.preventDefault();
      csvgenDrop.classList.remove("dragover");
      const file = event.dataTransfer?.files?.[0];
      if (file) {
        csvgenHandleFile(file);
      }
    });

    csvgenFileInput.addEventListener("change", () => {
      const file = csvgenFileInput.files?.[0];
      if (file) {
        csvgenHandleFile(file);
      }
    });

    csvgenGenerateBtn.addEventListener("click", () => {
      csvgenGenerateTemplates();
    });

    csvgenDownloadBtn.addEventListener("click", () => {
      if (!csvgenGeneratedBlob) {
        return;
      }
      const url = URL.createObjectURL(csvgenGeneratedBlob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "templates_raul_generados.csv";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    });

    csvgenResetBtn.addEventListener("click", () => {
      csvgenReset();
    });

    knowledgeUploadForm.addEventListener("submit", (event) => {
      event.preventDefault();
      uploadKnowledgeFile();
    });

    knowledgeSourcesList.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement)) {
        return;
      }
      const sourceLabel = target.dataset.knowledgeDelete;
      if (!sourceLabel) {
        return;
      }
      deleteKnowledgeSource(sourceLabel);
    });

    auditFilterBtn.addEventListener("click", () => {
      auditOffset = 0;
      loadAuditLog();
    });

    auditClearBtn.addEventListener("click", () => {
      auditActionFilter.value = "";
      auditOffset = 0;
      loadAuditLog();
    });

    auditPrevBtn.addEventListener("click", () => {
      auditOffset = Math.max(0, auditOffset - auditLimit);
      loadAuditLog();
    });

    auditNextBtn.addEventListener("click", () => {
      auditOffset += auditLimit;
      loadAuditLog();
    });

    security2faSetupBtn.addEventListener("click", () => {
      setup2fa();
    });

    security2faConfirmBtn.addEventListener("click", () => {
      confirm2fa();
    });

    loginForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      loginError.textContent = "";
      const submitBtn = loginForm.querySelector("button[type='submit']");
      const inputs = loginForm.querySelectorAll("input");
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span class="spinner btn-spinner" aria-hidden="true"></span><span>Procesando...</span>';
      inputs.forEach((i) => { i.disabled = true; });
      const formData = new FormData(loginForm);
      const username = String(formData.get("username") || "");
      const password = String(formData.get("password") || "");
      const code = String(formData.get("login_2fa_code") || "").trim();
      const restoreLogin = () => {
        submitBtn.disabled = false;
        submitBtn.innerHTML = pendingPreAuthToken ? "Verificar código" : "Entrar";
        inputs.forEach((i) => { i.disabled = false; });
      };
      try {
        let accessToken = "";
        if (pendingPreAuthToken) {
          const response = await fetch("/api/v1/auth/2fa/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pre_auth_token: pendingPreAuthToken, code }),
          });
          const payload = await response.json();
          if (!response.ok) {
            loginError.textContent = payload.detail || "Código inválido";
            showToast("error", payload.detail || "No se pudo validar el código");
            restoreLogin();
            return;
          }
          accessToken = String(payload.access_token || "");
        } else {
          const response = await fetch("/api/v1/auth/token", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
          });
          const payload = await response.json();
          if (response.status === 401) {
            loginError.textContent = "Credenciales incorrectas";
            showToast("error", "Credenciales incorrectas");
            restoreLogin();
            return;
          }
          if (response.status === 429) {
            loginError.textContent = payload.detail || "Demasiados intentos";
            showToast("error", payload.detail || "Demasiados intentos");
            restoreLogin();
            return;
          }
          if (!response.ok) {
            showToast("error", payload.detail || "No se pudo iniciar sesión");
            restoreLogin();
            return;
          }
          if (payload.requires_2fa) {
            pendingPreAuthToken = String(payload.pre_auth_token || "");
            login2faWrap.classList.remove("hidden");
            submitBtn.innerHTML = "Verificar código";
            showToast("info", "Ingresa tu código de autenticación.");
            restoreLogin();
            return;
          }
          accessToken = String(payload.access_token || "");
        }

        if (!accessToken) {
          showToast("error", "Respuesta de autenticación inválida");
          restoreLogin();
          return;
        }

        pendingPreAuthToken = null;
        login2faWrap.classList.add("hidden");
        login2faCode.value = "";
        setToken(accessToken);
        await loadBrandConfig();
        showPanel();
        setActiveTab("dashboard");
        showToast("success", "Sesión iniciada correctamente");
      } catch (error) {
        showToast("error", "Error de red al iniciar sesión");
        restoreLogin();
      }
    });

    tabs.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLButtonElement) || !target.dataset.tab) {
        return;
      }
      setActiveTab(target.dataset.tab);
    });

    tabs.addEventListener("keydown", (event) => {
      const tabBtns = Array.from(tabs.querySelectorAll(".tab"));
      const idx = tabBtns.indexOf(document.activeElement);
      if (idx === -1) return;
      if (event.key === "ArrowRight") {
        event.preventDefault();
        tabBtns[(idx + 1) % tabBtns.length].focus();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        tabBtns[(idx - 1 + tabBtns.length) % tabBtns.length].focus();
      } else if (event.key === "Home") {
        event.preventDefault();
        tabBtns[0].focus();
      } else if (event.key === "End") {
        event.preventDefault();
        tabBtns[tabBtns.length - 1].focus();
      }
    });

    function tickClock() {
      const now = new Date();
      const hh = String(now.getHours()).padStart(2, "0");
      const mm = String(now.getMinutes()).padStart(2, "0");
      const ss = String(now.getSeconds()).padStart(2, "0");
      navClock.textContent = `${hh}:${mm}:${ss}`;
    }

    (async function init() {
      setCampaignGoal(campaignGoal);
      renderSpeedSelection();
      renderCampaignActivityLog();
      renderTemplateChipsAndSnippets();
      applyTemplateType("lost");
      generateTemplatePreview(1);
      csvgenReset();
      convSummaryCard.classList.add("hidden");
      setConvEmptyState();
      setConvSearchMessage("");
      tickClock();
      setInterval(tickClock, 1000);

      const token = getToken();
      if (!token) {
        applyBrandConfig(BRAND_DEFAULTS);
        showLogin();
        return;
      }

      await loadBrandConfig();
      showPanel();
      setActiveTab("dashboard");
      showToast("info", "Sesión restaurada");
    })();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)
