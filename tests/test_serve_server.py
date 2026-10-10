from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest

from arch_blueprint.metrics import default_registry
from arch_blueprint.serve.server import ViewServer
from tests.conftest import EXAMPLE_PROJECT


@pytest.fixture(scope="module")
def server() -> Iterator[ViewServer]:
    running = ViewServer(
        str(EXAMPLE_PROJECT),
        ["app1", "app2", "plugins"],
        default_registry(),
    )
    thread = threading.Thread(target=running.serve_forever, daemon=True)
    thread.start()
    yield running
    running.shutdown()
    running.server_close()


def _get(server: ViewServer, path: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(server.url + path) as response:  # noqa: S310
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _post(server: ViewServer, data: Any) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(  # noqa: S310 — a local test server
        server.url + "/api/view",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_binds_loopback_only(server: ViewServer) -> None:
    assert server.url.startswith("http://127.0.0.1:")


def test_index(server: ViewServer) -> None:
    status, body = _get(server, "/")
    assert status == 200
    assert "<html" in body.decode()


def test_tree(server: ViewServer) -> None:
    status, body = _get(server, "/api/tree")
    assert status == 200
    tree = json.loads(body)
    assert tree["roots"] == ["app1", "app2", "plugins"]
    modules = {module["id"]: module["package"] for module in tree["modules"]}
    assert modules["app1"] is True
    assert modules["app1.models"] is False
    assert modules["plugins.auth"] is True


def test_view(server: ViewServer) -> None:
    status, view = _post(
        server,
        {"patterns": ["app1.**", "app2.**"], "folded": ["app1"], "metric": "fan_in"},
    )
    assert status == 200
    assert {node["id"] for node in view["nodes"]} == {"app1", "app2.service"}
    assert view["cli"].endswith("--metric fan_in")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"patterns": ["app1.**"], "links": "namespace"}, "links must be one of"),
        ({"patterns": ["app1.nothing.*"]}, "no modules matched"),
        ({"patterns": ["nope.**"]}, "no package 'nope'"),
        ({"patterns": ["app1.**"], "metric": "nope"}, "unknown metric 'nope'"),
        ([], "a JSON object"),
    ],
)
def test_view_errors(server: ViewServer, data: Any, message: str) -> None:
    status, body = _post(server, data)
    assert status == 400
    assert message in body["error"]
    assert _post(server, {"patterns": ["app1.**"]})[0] == 200


def test_bad_json(server: ViewServer) -> None:
    request = urllib.request.Request(  # noqa: S310
        server.url + "/api/view",
        data=b"{",
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request)  # noqa: S310
    assert error.value.code == 400


@pytest.mark.parametrize(
    "path",
    ["/static/../server.py", "/static/%2e%2e/server.py", "/static/nope.js", "/nope"],
)
def test_not_found(server: ViewServer, path: str) -> None:
    status, _ = _get(server, path)
    assert status == 404


def test_page_assets_are_served(server: ViewServer) -> None:
    """Every script and stylesheet the page names is there: the page works offline."""
    _, page = _get(server, "/")
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', page.decode())
    assert "/static/vendor/cytoscape.min.js" in assets
    assert "/static/viewer.js" in assets
    for asset in assets:
        status, body = _get(server, asset)
        assert (asset, status) == (asset, 200)
        assert body
