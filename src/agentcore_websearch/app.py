"""FastAPI + Jinja2 + HTMX web app.

Route handlers are thin: read state, call into the library modules, render
a template. No business logic here — that lives in provisioning.py,
raw_explorer.py, compare.py, ledger.py.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from agentcore_websearch import provisioning
from agentcore_websearch.agent_loop import run_agent_loop
from agentcore_websearch.compare import compare_factual_vs_open_ended, sweep_max_results
from agentcore_websearch.ledger import Ledger
from agentcore_websearch.models import KnowledgeGraphFact
from agentcore_websearch.native_web_search import search as native_search
from agentcore_websearch.raw_explorer import ledgered_call_tool, list_tools

BASE_DIR = Path(__file__).parent

app = FastAPI(title="AgentCore Web Search Lab")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

ledger = Ledger(data_dir=Path("data"))


def _serialize_result(r) -> dict:
    return {
        "kind": "knowledge_graph" if isinstance(r, KnowledgeGraphFact) else "web",
        "title": getattr(r, "title", None),
        "url": getattr(r, "url", None),
        "text": r.text,
        "published_date": r.published_date,
    }


def _serialize_comparisons(comparisons) -> list[dict]:
    return [
        {
            "label": c.label,
            "query": c.query,
            "cache_hit": c.cache_hit,
            "knowledge_graph_count": c.knowledge_graph_count,
            "web_count": c.web_count,
            "results": [_serialize_result(r) for r in c.results],
        }
        for c in comparisons
    ]


async def _gateway_status() -> dict | None:
    return await asyncio.to_thread(provisioning.status)


async def _first_tool_name(gateway_url: str) -> str:
    tools = await list_tools(gateway_url)
    return tools[0].name


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    gateway = await _gateway_status()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"active": "dashboard", "gateway": gateway, "totals": ledger.totals()},
    )


@app.get("/gateway", response_class=HTMLResponse)
async def gateway_page(request: Request):
    gateway = await _gateway_status()
    return templates.TemplateResponse(
        request, "gateway.html", {"active": "gateway", "gateway": gateway}
    )


@app.post("/gateway", response_class=HTMLResponse)
async def gateway_provision(request: Request):
    result = await asyncio.to_thread(provisioning.setup)
    return templates.TemplateResponse(
        request,
        "fragments/gateway_result.html",
        {"message": "Provisioned.", "result_json": json.dumps(result, indent=2)},
    )


@app.post("/gateway/teardown", response_class=HTMLResponse)
async def gateway_teardown(request: Request):
    await asyncio.to_thread(provisioning.teardown)
    return templates.TemplateResponse(
        request,
        "fragments/gateway_result.html",
        {"message": "Torn down.", "result_json": "{}"},
    )


@app.get("/tools", response_class=HTMLResponse)
async def tools_page(request: Request):
    gateway = await _gateway_status()
    gateway_ready = bool(gateway and gateway["gateway_status"] == "READY")
    tools = []
    if gateway_ready:
        raw_tools = await list_tools(gateway["gateway_url"])
        tools = [
            {"name": t.name, "inputSchema": t.inputSchema} for t in raw_tools
        ]
    return templates.TemplateResponse(
        request,
        "tools.html",
        {"active": "tools", "gateway_ready": gateway_ready, "tools": tools},
    )


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    gateway = await _gateway_status()
    gateway_ready = bool(gateway and gateway["gateway_status"] == "READY")
    tool_name = None
    if gateway_ready:
        tool_name = await _first_tool_name(gateway["gateway_url"])
    return templates.TemplateResponse(
        request,
        "search.html",
        {"active": "search", "gateway_ready": gateway_ready, "tool_name": tool_name},
    )


@app.post("/search", response_class=HTMLResponse)
async def search_run(request: Request, query: str = Form(...), max_results: int = Form(5)):
    gateway = await _gateway_status()
    tool_name = await _first_tool_name(gateway["gateway_url"])
    start = time.perf_counter()
    response, cache_hit = await ledgered_call_tool(
        ledger, gateway["gateway_url"], tool_name, {"query": query, "maxResults": max_results}
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return templates.TemplateResponse(
        request,
        "fragments/search_result.html",
        {
            "response_json": json.dumps(response, indent=2),
            "cache_hit": cache_hit,
            "elapsed_ms": elapsed_ms,
        },
    )


@app.get("/native-search", response_class=HTMLResponse)
async def native_search_page(request: Request):
    return templates.TemplateResponse(
        request, "native_search.html", {"active": "native_search"}
    )


@app.post("/native-search", response_class=HTMLResponse)
async def native_search_run(
    request: Request,
    prompt: str = Form(...),
    external_web_access: bool = Form(False),
):
    start = time.perf_counter()
    result = await asyncio.to_thread(native_search, ledger, prompt, external_web_access)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return templates.TemplateResponse(
        request,
        "fragments/native_search_result.html",
        {
            "answer_text": result.answer_text,
            "citations": result.citations,
            "external_web_access": result.external_web_access,
            "raw_json": json.dumps(result.raw, indent=2),
            "cache_hit": result.cache_hit,
            "elapsed_ms": elapsed_ms,
        },
    )


@app.get("/compare", response_class=HTMLResponse)
async def compare_page(request: Request):
    gateway = await _gateway_status()
    gateway_ready = bool(gateway and gateway["gateway_status"] == "READY")
    return templates.TemplateResponse(
        request, "compare.html", {"active": "compare", "gateway_ready": gateway_ready}
    )


@app.post("/compare", response_class=HTMLResponse)
async def compare_run(
    request: Request,
    factual_query: str = Form(...),
    open_ended_query: str = Form(...),
):
    gateway = await _gateway_status()
    comparisons = await compare_factual_vs_open_ended(
        ledger, gateway["gateway_url"], factual_query, open_ended_query
    )
    return templates.TemplateResponse(
        request,
        "fragments/compare_result.html",
        {"comparisons": _serialize_comparisons(comparisons)},
    )


@app.post("/compare/sweep", response_class=HTMLResponse)
async def compare_sweep(request: Request, sweep_query: str = Form(...)):
    gateway = await _gateway_status()
    comparisons = await sweep_max_results(ledger, gateway["gateway_url"], sweep_query)
    return templates.TemplateResponse(
        request,
        "fragments/sweep_result.html",
        {"comparisons": _serialize_comparisons(comparisons)},
    )


@app.get("/agent", response_class=HTMLResponse)
async def agent_page(request: Request):
    gateway = await _gateway_status()
    gateway_ready = bool(gateway and gateway["gateway_status"] == "READY")
    return templates.TemplateResponse(
        request,
        "agent.html",
        {
            "active": "agent",
            "gateway_ready": gateway_ready,
            "prompt": request.query_params.get("prompt"),
        },
    )


@app.get("/agent/stream")
async def agent_stream(request: Request, prompt: str):
    gateway = await _gateway_status()
    gateway_url = gateway["gateway_url"]
    turn_template = templates.get_template("fragments/agent_turn.html")

    async def event_generator():
        agen = run_agent_loop(gateway_url, ledger, prompt)
        try:
            async for turn in agen:
                if await request.is_disconnected():
                    break
                html = turn_template.render(turn=turn)
                yield "\n".join(f"data: {line}" for line in html.splitlines()) + "\n\n"
        finally:
            await agen.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/costs", response_class=HTMLResponse)
async def costs_page(request: Request):
    return templates.TemplateResponse(
        request, "costs.html", {"active": "costs", "totals": ledger.totals()}
    )
