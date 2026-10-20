"""`nov serve`: server-rendered pages over the Service, with htmx for in-place updates.

Every form works without JavaScript (POST, then a redirect back); with htmx, job
buttons post in place and show the result in the notice area. The jobs drawer is
pushed over Server-Sent Events whenever a job changes, and an `active` event (a job
started or ended) makes the page reload its main region, so counts and buttons follow.

The server listens on 127.0.0.1 only. A POST whose Origin is another site is
refused, so a web page cannot start jobs through the visitor's browser.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from novel_core import Kind
from novel_sources.backends import BACKENDS
from starlette.concurrency import run_in_threadpool

from novel_app.jobs import JobPanel, JobRunning, JobState
from novel_app.notation import parse_range
from novel_app.pages import CELL_LABELS, CellState, source_label
from novel_app.service import Service, UserError

HERE = Path(__file__).parent
STREAM_EVERY = 1.0

# The fields each kind of job takes from a web form; anything else is ignored.
WEB_JOBS: dict[str, tuple[str, ...]] = {
    "add": ("url", "novel", "lang", "backend"),
    "sync": ("novel",),
    "build-site": (),
    "build-epub": ("novel",),
    "build-audio": ("novel",),
    "build-volumes": ("novel",),
    "audio-retag": ("novel",),
}
JOB_LABELS = {
    "add": "Add source",
    "sync": "Sync",
    "build-site": "Build site",
    "build-epub": "Build EPUB",
    "build-audio": "Build audio",
    "build-volumes": "Build M4B volumes",
    "audio-retag": "Retag MP3s",
}


def create_app(service: Service) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        service.runner.board.reconcile()
        yield
        await run_in_threadpool(service.runner.shutdown)

    app = FastAPI(title="Novel library", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.mount("/site-assets", StaticFiles(packages=[("novel_publish", "static")]), name="site-assets")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["ago"] = _ago
    templates.env.globals.update(
        job_labels=JOB_LABELS, cell_labels=CELL_LABELS, CellState=CellState, Kind=Kind, JobState=JobState,
        backends=BACKENDS, owns=service.runner.owns, source_label=source_label,
    )  # fmt: skip

    def page(request: Request, name: str, status: int = 200, **context) -> HTMLResponse:
        context.setdefault("jobs", service.jobs())
        context.setdefault("job_panel", service.job_panel())
        return templates.TemplateResponse(
            request, name, {"notice": request.query_params.get("notice"), **context}, status_code=status
        )

    def refused(request: Request, message: str, status: int) -> HTMLResponse:
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(request, "_notice.html", {"error": message}, status_code=status)
        return page(request, "error.html", status, message=message)

    def done(request: Request, notice: str, back: str) -> Response:
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(request, "_notice.html", {"notice": notice})
        return RedirectResponse(_with_query(back, notice=notice), status_code=303)

    @app.middleware("http")
    async def same_origin_posts(request: Request, call_next: Callable):
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and urlsplit(origin).netloc != request.url.netloc:
            return PlainTextResponse("cross-site request refused", status_code=403)
        return await call_next(request)

    @app.exception_handler(UserError)
    async def user_error(request: Request, e: UserError):
        return refused(request, str(e), 400)

    @app.exception_handler(JobRunning)
    async def job_running(request: Request, e: JobRunning):
        return refused(request, str(e), 409)

    # -- pages -----------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def library(request: Request):
        rows = await run_in_threadpool(service.library)
        return page(request, "library.html", rows=rows)

    @app.get("/novels/{novel}", response_class=HTMLResponse)
    async def novel(request: Request, novel: str):
        return page(request, "novel.html", novel=await run_in_threadpool(service.novel, novel))

    @app.get("/novels/{novel}/compare", response_class=HTMLResponse)
    async def compare(request: Request, novel: str, number: int, left: int | None = None, right: int | None = None):
        c = await run_in_threadpool(service.compare, novel, number, left, right)
        return page(request, "compare.html", slug=novel, c=c)

    @app.get("/add", response_class=HTMLResponse)
    async def add_form(request: Request):
        return page(request, "add.html", spec=None, form={})

    @app.post("/add", response_class=HTMLResponse)
    async def add_preview(
        request: Request,
        url: str = Form(),
        lang: str = Form("en"),
        backend: str = Form(""),
        novel: str = Form(""),
    ):
        spec = await run_in_threadpool(service.preview_add, url, lang, backend or None)
        form = {"url": url, "lang": lang, "backend": backend, "novel": novel}
        return page(request, "add.html", spec=spec, form=form, novels=service.novels())

    # -- writes ------------------------------------------------------------------

    @app.post("/novels/{novel}/priority")
    async def priority(request: Request, novel: str, source: int = Form(), move: str = Form()):
        order = [r.source.id for r in service.priority(novel)]
        if source not in order or move not in ("up", "down"):
            raise UserError(f"cannot move source {source} {move}")
        i = order.index(source)
        j = max(0, i - 1) if move == "up" else min(len(order) - 1, i + 1)
        order[i], order[j] = order[j], order[i]
        await run_in_threadpool(service.priority, novel, order)
        return RedirectResponse(f"/novels/{novel}#sources", status_code=303)

    @app.post("/novels/{novel}/pin")
    async def pin(request: Request, novel: str, numbers: str = Form(), source: int = Form(), back: str = Form("")):
        try:
            keys = parse_range(numbers)
        except ValueError as e:
            raise UserError(str(e)) from e
        await run_in_threadpool(service.pin, novel, keys, source)
        return done(request, f"{keys.start}-{keys.end} pinned to source {source}", back or f"/novels/{novel}")

    @app.post("/novels/{novel}/unpin")
    async def unpin(request: Request, novel: str, numbers: str = Form()):
        try:
            keys = parse_range(numbers)
        except ValueError as e:
            raise UserError(str(e)) from e
        await run_in_threadpool(service.unpin, novel, keys)
        return done(request, f"{keys.start}-{keys.end} unpinned", f"/novels/{novel}")

    # -- jobs ----------------------------------------------------------------------

    @app.post("/jobs")
    async def start_job(request: Request):
        form = await request.form()
        kind = str(form.get("kind", ""))
        if kind not in WEB_JOBS:
            raise UserError(f"no job kind {kind!r}")
        args = {f: str(form[f]) for f in WEB_JOBS[kind] if form.get(f)}
        job_id = await run_in_threadpool(lambda: service.start(kind, **args))
        return done(request, f"started job {job_id}: {JOB_LABELS[kind]} {args.get('novel', '')}".rstrip(), _back(form))

    @app.post("/jobs/{job_id}/cancel")
    async def cancel(request: Request, job_id: int):
        form = await request.form()
        if not service.cancel(job_id):
            raise UserError(f"job {job_id} is not running in this server")
        return done(request, f"job {job_id} will stop after its current item", _back(form))

    @app.post("/jobs/{job_id}/rerun")
    async def rerun(request: Request, job_id: int):
        form = await request.form()
        new = await run_in_threadpool(service.rerun, job_id)
        return done(request, f"started job {new} (again as job {job_id})", _back(form))

    @app.get("/jobs/{job_id}/log", response_class=PlainTextResponse)
    async def job_log(job_id: int):
        return service.job_log(job_id)

    @app.get("/jobs/stream")
    async def job_stream(request: Request):
        def render(panel: JobPanel) -> str:
            return templates.get_template("_jobs.html").render(job_panel=panel, owns=service.runner.owns)

        async def events() -> AsyncIterator[str]:
            async for event in job_events(service, render, request.is_disconnected):
                yield event

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})

    return app


async def job_events(
    service: Service,
    render: Callable[[JobPanel], str],
    disconnected: Callable,
    every: float = STREAM_EVERY,
) -> AsyncIterator[str]:
    """SSE events: `jobs` (the drawer's HTML) when it changes, `active` when a job starts or ends."""
    shown, active = None, None
    while not await disconnected():
        panel = await run_in_threadpool(service.job_panel)
        html = render(panel)
        if html != shown:
            shown = html
            yield sse("jobs", html)
        now_active = {j.id for j in panel.attention if j.state.active}
        if active is not None and active != now_active:
            yield sse("active", "")
        active = now_active
        await asyncio.sleep(every)


def sse(event: str, data: str) -> str:
    lines = data.splitlines() or [""]
    return f"event: {event}\n" + "".join(f"data: {line}\n" for line in lines) + "\n"


def _back(form) -> str:
    back = str(form.get("back", "/"))
    return back if back.startswith("/") and not back.startswith("//") else "/"


def _with_query(url: str, **params: str) -> str:
    base, _, fragment = url.partition("#")
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode(params)}" + (f"#{fragment}" if fragment else "")


def _ago(ts: float | None) -> str:
    if ts is None:
        return "never"
    seconds = time.time() - ts
    if seconds < 90:
        return "just now"
    if seconds < 3600:
        return f"{seconds / 60:.0f} min ago"
    if seconds < 86400:
        return f"{seconds / 3600:.0f} h ago"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
