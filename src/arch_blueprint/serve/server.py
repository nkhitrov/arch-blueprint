"""The viewer's local HTTP server: the page, the package tree, and views.

Standard library only, bound to the loopback interface: it serves one person's
project to their own browser. Every view is built by :func:`build_view`; the
server only parses requests, keeps the grimp builds it has made, and turns the
expected failures into a ``400`` with the message the CLI would print.
"""

from __future__ import annotations

import json
import mimetypes
import threading
from collections import OrderedDict
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final, Optional
from urllib.parse import unquote, urlsplit

from arch_blueprint.extract.levels import ancestors
from arch_blueprint.extract.source import GrimpSource, PackageNotFoundError
from arch_blueprint.metrics import MetricRegistry
from arch_blueprint.serve.view import ViewRequest, build_view, cli_command

STATIC_DIR: Final = Path(__file__).resolve().parent / "static"

#: How many grimp builds (one per distinct set of patterns) are kept.
_SOURCES_KEPT: Final = 4

#: A view request is a few patterns; anything this large is not one.
_MAX_BODY: Final = 1 << 20


class ViewServer(ThreadingHTTPServer):
    """Serves the viewer of the project in ``project_dir`` on ``127.0.0.1``.

    ``roots`` are the top-level packages the tree offers. ``port`` 0 picks a
    free one; :attr:`url` says which.
    """

    daemon_threads = True

    def __init__(
        self,
        project_dir: str,
        roots: Sequence[str],
        registry: MetricRegistry,
        port: int = 0,
    ) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.project_dir = project_dir
        self.roots = list(roots)
        self.registry = registry
        self._sources: OrderedDict[tuple[str, ...], GrimpSource] = OrderedDict()
        # One request at a time touches the interpreter state GrimpSource
        # borrows (sys.path, sys.modules): it is process-wide.
        self._lock = threading.Lock()

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host!s}:{port}"

    def tree(self) -> dict[str, Any]:
        """The modules under the roots, each marked whether it is a package."""
        with self._lock:
            source = self._source(tuple(f"{root}.**" for root in self.roots))
            modules = {
                name for root in self.roots for name in source.modules_under(root)
            }
        names = modules | {prefix for name in modules for prefix in ancestors(name)}
        packages = {prefix for name in names for prefix in ancestors(name)}
        return {
            "project": self.project_dir,
            "roots": self.roots,
            "modules": [
                {"id": name, "package": name in packages} for name in sorted(names)
            ],
        }

    def view(self, request: ViewRequest, metric: Optional[str]) -> dict[str, Any]:
        """A view and the ``draw`` command closest to it."""
        with self._lock:
            view = build_view(self._source(request.patterns), request, self.registry)
        if metric is not None and metric not in (
            *view["metrics"]["node"],
            *view["metrics"]["link"],
        ):
            msg = f"unknown metric {metric!r}"
            raise ValueError(msg)
        view["cli"] = cli_command(self.project_dir, request, metric)
        return view

    def _source(self, patterns: tuple[str, ...]) -> GrimpSource:
        source = self._sources.pop(patterns, None)
        if source is None:
            source = GrimpSource(self.project_dir, patterns)
        self._sources[patterns] = source
        while len(self._sources) > _SOURCES_KEPT:
            self._sources.popitem(last=False)
        return source


class _Handler(BaseHTTPRequestHandler):
    server: ViewServer

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/tree":
            self._json(HTTPStatus.OK, self.server.tree())
        elif path == "/":
            self._file(STATIC_DIR / "index.html")
        elif path.startswith("/static/"):
            self._file(STATIC_DIR / unquote(path[len("/static/") :]))
        else:
            self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/view":
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        try:
            data = self._body()
            request = ViewRequest.from_json(data)
            metric = data.get("metric")
            view = self.server.view(request, None if metric is None else str(metric))
        except PackageNotFoundError as error:
            self._error(
                HTTPStatus.BAD_REQUEST,
                f"no package {error.package!r} in {self.server.project_dir}",
            )
        except (ValueError, ImportError) as error:
            self._error(HTTPStatus.BAD_REQUEST, str(error))
        else:
            self._json(HTTPStatus.OK, view)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > _MAX_BODY:
            msg = "request too large"
            raise ValueError(msg)
        try:
            data = json.loads(self.rfile.read(length) or b"null")
        except json.JSONDecodeError as error:
            msg = f"not JSON: {error}"
            raise ValueError(msg) from error
        if not isinstance(data, dict):
            msg = "a view request is a JSON object"
            raise ValueError(msg)
        return data

    def _file(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_relative_to(STATIC_DIR) or not resolved.is_file():
            self._error(HTTPStatus.NOT_FOUND, "not found")
            return
        content_type = (
            mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        )
        if content_type.startswith("text/") or content_type.endswith("javascript"):
            content_type += "; charset=utf-8"
        self._send(HTTPStatus.OK, content_type, resolved.read_bytes())

    def _json(self, status: HTTPStatus, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(status, "application/json; charset=utf-8", body)

    def _error(self, status: HTTPStatus, message: str) -> None:
        self._json(status, {"error": message})

    def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Silent: the terminal running ``serve`` is not a request log."""
