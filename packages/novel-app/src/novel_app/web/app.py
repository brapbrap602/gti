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
from markdown_it import MarkdownIt
from markupsafe import Markup
from novel_core import Kind
from novel_sources.backends import BACKENDS
from novel_translate.glossary import AddAlias, AddTerm, Category, Edit, Status, UpdateTerm
from novel_translate.setups import CONTEXTS, DATA_COLLECTION, REASONING, SetupError, TranslatorSetup
from starlette.concurrency import run_in_threadpool

from novel_app.comparing import all_chapters, columns, setup_name, words
from novel_app.glossary_page import TABS
from novel_app.jobs import JobPanel, JobRunning, JobState
from novel_app.notation import parse_range
from novel_app.pages import CELL_LABELS, CellState, align_range_command, findings_text, reclean_command, source_label
from novel_app.service import Service, UserError

HERE = Path(__file__).parent
STREAM_EVERY = 1.0
# Judgements are Markdown; raw HTML in them is shown as text, not run.
MARKDOWN = MarkdownIt("commonmark", {"html": False}).enable("table")

# The fields each kind of job takes from a web form; anything else is ignored.
WEB_JOBS: dict[str, tuple[str, ...]] = {
    "add": ("url", "novel", "lang", "backend"),
    "sync": ("novel",),
    "build-site": (),
    "build-epub": ("novel",),
    "build-audio": ("novel",),
    "build-volumes": ("novel",),
    "audio-retag": ("novel",),
    "glossary-build": ("novel", "model", "cap"),
    "translate": ("novel", "setup", "range", "cap", "workers"),
}
JOB_LABELS = {
    "add": "Add source",
    "sync": "Sync",
    "build-site": "Build site",
    "build-epub": "Build EPUB",
    "build-audio": "Build audio",
    "build-volumes": "Build M4B volumes",
    "audio-retag": "Retag MP3s",
    "glossary-build": "Build glossary",
    "translate": "Translate",
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
    templates.env.filters["markdown"] = lambda text: Markup(MARKDOWN.render(text))
    templates.env.globals.update(
        job_labels=JOB_LABELS, cell_labels=CELL_LABELS, CellState=CellState, Kind=Kind, JobState=JobState,
        backends=BACKENDS, owns=service.runner.owns, source_label=source_label,
        contexts=CONTEXTS, reasoning_levels=REASONING, data_collection=DATA_COLLECTION,
        setup_name=setup_name, words=words, align_range_command=align_range_command,
        findings_text=findings_text, reclean_command=reclean_command,
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
        n = await run_in_threadpool(service.novel, novel)
        return page(
            request, "novel.html", novel=n, glossary=await run_in_threadpool(service.glossary_counts, novel),
            translate=await run_in_threadpool(service.translate_panel, novel),
            comparisons=len(await run_in_threadpool(service.comparisons, novel)),
            prefill={"setup": request.query_params.get("setup", ""), "range": request.query_params.get("range", "")},
        )  # fmt: skip

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

    # -- translation ---------------------------------------------------------------

    @app.post("/novels/{novel}/publish")
    async def publish(request: Request, novel: str, source: int = Form(), on: str = Form()):
        await run_in_threadpool(service.set_published, novel, source, on == "on")
        state = "published: rank it in the order above" if on == "on" else "unpublished"
        return done(request, f"source {source} {state}", f"/novels/{novel}#sources")

    @app.post("/novels/{novel}/setups")
    async def add_setup(
        request: Request,
        novel: str,
        model: str = Form(),
        prompt: str = Form("v1"),
        context: str = Form("parallel"),
        reasoning: str = Form("off"),
        data_collection: str = Form("allow"),
    ):
        try:
            setup = TranslatorSetup(model.strip(), prompt, context, reasoning, data_collection)
        except SetupError as e:
            raise UserError(str(e)) from e
        source = await run_in_threadpool(service.add_setup, novel, setup)
        return done(request, f"setup added as source {source} (unpublished)", f"/novels/{novel}#translate")

    @app.get("/novels/{novel}/translate/estimate", response_class=HTMLResponse)
    async def translate_estimate(request: Request, novel: str, setup: str = "", range: str = ""):
        try:
            e = await run_in_threadpool(service.translate_estimate, novel, setup, range)
            context = {"estimate": e, "error": None, "slug": novel}
        except UserError as err:
            context = {"estimate": None, "error": str(err), "slug": novel}
        return templates.TemplateResponse(request, "_estimate.html", context)

    # -- model comparisons -----------------------------------------------------------

    @app.get("/novels/{novel}/comparisons", response_class=HTMLResponse)
    async def comparisons(request: Request, novel: str):
        runs = await run_in_threadpool(service.comparisons, novel)
        return page(request, "comparisons.html", slug=novel, runs=runs, columns=columns(runs), chapters=all_chapters(runs))

    @app.get("/novels/{novel}/comparisons/{ref}", response_class=HTMLResponse)
    async def comparison_chapter(request: Request, novel: str, ref: str):
        screen = await run_in_threadpool(service.comparison_chapter, novel, ref)
        shown = request.query_params.getlist("show")
        return page(request, "comparison_chapter.html", slug=novel, s=screen, shown=set(shown) if shown else None)

    # -- glossary ------------------------------------------------------------------

    @app.get("/novels/{novel}/glossary", response_class=HTMLResponse)
    async def glossary(request: Request, novel: str, tab: str = "review", q: str = "", category: str = ""):
        g = await run_in_threadpool(service.glossary_page, novel, tab, q.strip(), _category(category))
        rows = await run_in_threadpool(service.setups, novel)
        return page(request, "glossary.html", page=g, tabs=TABS, categories=list(Category), setups=rows)

    @app.post("/novels/{novel}/glossary")
    async def glossary_add(
        request: Request,
        novel: str,
        zh: str = Form(),
        en: str = Form(),
        category: str = Form("other"),
        aliases: str = Form(""),
        back: str = Form(""),
    ):
        names = tuple(a.strip() for a in aliases.replace("，", ",").split(",") if a.strip())
        edit = AddTerm(zh, en, _category(category) or Category.OTHER, aliases=names)
        await run_in_threadpool(service.glossary_edit, novel, [edit])
        return done(request, f"added {zh} → {en}", _local(back, f"/novels/{novel}/glossary"))

    @app.post("/novels/{novel}/glossary/bulk")
    async def glossary_bulk(request: Request, novel: str):
        form = await request.form()
        ids = [int(i) for i in form.getlist("ids")]
        action, category = str(form.get("action", "")), _category(str(form.get("category", "")))
        if not ids:
            raise UserError("tick some terms first")
        if action == "accept":
            rows = [await run_in_threadpool(service.glossary_row, novel, i) for i in ids]
            edits = [UpdateTerm(r.term.id, en=r.top_llm, status=Status.ACCEPTED) for r in rows]
        elif action in ("lock", "reject"):
            edits = [UpdateTerm(i, status=Status.LOCKED if action == "lock" else Status.REJECTED) for i in ids]
        elif action == "category" and category is not None:
            edits = [UpdateTerm(i, category=category) for i in ids]
        else:
            raise UserError(f"cannot {action or 'do that'} in bulk" + (" without a category" if action == "category" else ""))
        await run_in_threadpool(service.glossary_edit, novel, edits)
        return done(request, f"{len(ids)} terms updated", _local(str(form.get("back", "")), f"/novels/{novel}/glossary"))

    @app.post("/novels/{novel}/glossary/{term_id}")
    async def glossary_term(request: Request, novel: str, term_id: int):
        form = await request.form()
        action = str(form.get("action", ""))
        edits = _term_edits(term_id, action, form)
        await run_in_threadpool(service.glossary_edit, novel, edits)
        back = _local(str(form.get("back", "")), f"/novels/{novel}/glossary")
        if request.headers.get("HX-Request"):
            row = await run_in_threadpool(service.glossary_row, novel, term_id)
            return templates.TemplateResponse(
                request, "_term.html", {"row": row, "slug": novel, "back": back, "categories": list(Category)}
            )
        return RedirectResponse(back, status_code=303)

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
    return _local(str(form.get("back", "/")), "/")


def _local(url: str, default: str) -> str:
    """A path on this server, or the default: a form's `back` never sends the browser elsewhere."""
    return url if url.startswith("/") and not url.startswith("//") else default


def _category(text: str) -> Category | None:
    if not text:
        return None
    try:
        return Category(text)
    except ValueError as e:
        raise UserError(f"no category {text!r}") from e


def _term_edits(term_id: int, action: str, form) -> list[Edit]:
    """The glossary edits one action on the page stands for."""
    match action:
        case "save":
            return [UpdateTerm(term_id, en=str(form.get("en", "")))]
        case "pick":
            return [UpdateTerm(term_id, en=str(form.get("en", "")), status=Status.ACCEPTED)]
        case "accept":
            return [UpdateTerm(term_id, status=Status.ACCEPTED)]
        case "lock":
            return [UpdateTerm(term_id, status=Status.LOCKED)]
        case "reject":
            return [UpdateTerm(term_id, status=Status.REJECTED)]
        case "revive":  # a term after all: the user decides its rendering
            return [UpdateTerm(term_id, status=Status.NEEDS_REVIEW)]
        case "details":
            edits: list[Edit] = [
                UpdateTerm(
                    term_id,
                    category=_category(str(form.get("category", ""))),
                    gender=str(form.get("gender", "")),
                    notes=str(form.get("notes", "")),
                )
            ]
            if alias := str(form.get("alias", "")).strip():
                edits.append(AddAlias(term_id, alias))
            return edits
    raise UserError(f"no glossary action {action!r}")


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
