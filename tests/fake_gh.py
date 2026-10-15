"""
A fake `gh` executable for tests, so nothing touches the network.

install_fake_gh writes a script named `gh` into a directory, puts that
directory first on PATH, and serves canned responses described by a routes
dict. The script is run by the test's own Python interpreter.
"""

import json
import os
import stat
import sys

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "github")

SCRIPT = """#!{python}
import json, os, sys

config = json.load(open(os.path.join({config_dir!r}, "config.json")))
args = sys.argv[1:]
with open(os.path.join({config_dir!r}, "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\\n")

if args[:2] == ["auth", "status"]:
    sys.stderr.write("not logged in\\n" if config["auth"] else "")
    sys.exit(1 if config["auth"] else 0)

if args[0] == "api":
    key = args[1]
    if key == "graphql":
        values = dict(a.split("=", 1) for a in args if "=" in a and a[0] != "-")
        key = "graphql:" + values["owner"] + "/" + values["name"]
    route = config["routes"].get(key)
    if route is None:
        sys.stderr.write("gh: Not Found (HTTP 404)\\n")
        sys.exit(1)
    if "error" in route:
        sys.stdout.write(route.get("stdout", ""))
        sys.stderr.write(route["error"])
        sys.exit(1)
    if "raw" in route:
        sys.stdout.write(route["raw"])
        sys.exit(0)
    if "graphql_pages" in route:
        # like gh --paginate: one response per page, back to back
        for nodes in route["graphql_pages"]:
            if isinstance(nodes, str):  # a fixture file holding the nodes
                nodes = json.load(open(os.path.join({fixtures!r}, nodes)))
            page = {{"repository": {{"pullRequests": {{"nodes": nodes}}}}}}
            sys.stdout.write(json.dumps({{"data": page}}))
        sys.exit(0)
    if "body" in route:
        sys.stdout.write(json.dumps(route["body"]))
        sys.exit(0)
    pages = [open(os.path.join({fixtures!r}, p)).read() for p in route["pages"]]
    if "--paginate" in args and route.get("shape") == "merged":
        merged = []
        for page in pages:
            merged.extend(json.loads(page))
        sys.stdout.write(json.dumps(merged))
    elif "--paginate" in args and route.get("shape") == "newline":
        sys.stdout.write("\\n".join(json.dumps(json.loads(p)) for p in pages) + "\\n")
    else:
        sys.stdout.write("".join(json.dumps(json.loads(p)) for p in pages))
    sys.exit(0)

sys.exit(2)
"""


def install_fake_gh(tmp_path, monkeypatch, routes=None, auth_ok=True):
    """
    Install a fake gh at the front of PATH.
    @param tmp_path: a scratch directory for the script and its config
    @param monkeypatch: pytest's monkeypatch, used to set PATH
    @param routes: {api path: {"pages": [fixture files], "shape": "merged" |
        "newline" | "concatenated"}, {"error": stderr text} or {"raw": stdout
        text printed as is} or {"body": a JSON value printed as is}}. GraphQL
        calls use the key "graphql:owner/name" and {"graphql_pages": [one list
        of pull request nodes (or fixture file name) per page]}.
    @param auth_ok: whether `gh auth status` succeeds
    @returns: a function that returns the list of argument lists gh was run with
    """
    bin_dir = tmp_path / "fake-bin"
    config_dir = tmp_path / "fake-gh-config"
    bin_dir.mkdir()
    config_dir.mkdir()
    (config_dir / "config.json").write_text(
        json.dumps({"auth": 0 if auth_ok else 1, "routes": routes or {}})
    )
    script = bin_dir / "gh"
    script.write_text(
        SCRIPT.format(
            python=sys.executable, config_dir=str(config_dir), fixtures=FIXTURES
        )
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])

    def calls():
        log = config_dir / "calls.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    return calls
