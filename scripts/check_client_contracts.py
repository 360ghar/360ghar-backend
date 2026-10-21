"""Check client repos against docs/openapi.json.

Usage:
    uv run python scripts/check_client_contracts.py REPO [REPO ...]
        [--openapi docs/openapi.json] [--tool-names PATH]

For each repo the script reads source files (TypeScript and Dart), extracts API path
literals, and reports every literal that has no matching path and method in the OpenAPI
document. Findings are:
  - unknown path: no operation has this path.
  - wrong method: the path exists, but not with this method.
  - undeclared query key: the operation does not declare a query key that the call sends.
    Keys come from a `?a=1&b=2` string and, for TS clients with generated types, from a
    static `query: {...}` or `params: {...}` object literal.
  - unregistered tool: a `callTool('name')` literal that no MCP tool registers.
The exit code is 1 when there is any finding.

The extractor is static. It does not follow variables, so a path built at runtime is not
seen. A literal that is only the start of a longer route (a prefix of a real path) is
accepted as a fragment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPENAPI = BACKEND_ROOT / "docs" / "openapi.json"
DEFAULT_TOOL_NAMES = BACKEND_ROOT / "chatgpt-widgets" / "src" / "generated" / "tool-names.json"
API_PREFIX = "/api/v1"
METHODS = {"get", "post", "put", "patch", "delete"}

SKIP_DIRS = {
    "node_modules", "dist", "build", ".dart_tool", ".git", "generated", "openapi", "coverage",
    "test", "tests", "__tests__", "e2e", "mocks", "__mocks__", "playwright-report", "test-results",
    "ios", "android", "web_test", ".next", ".astro", "docs", "plans", "tmp", "artifacts", "outputs",
    "scripts", "tool", "devtools",
}
SKIP_FILE = re.compile(r"(\.test\.|\.spec\.|\.gen\.|\.d\.ts$|\.g\.dart$|\.freezed\.dart$|_test\.dart$)")
SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".astro", ".dart"}
DART_PATH_FILE = re.compile(r"(api_paths|endpoints|api_constants|api_endpoints)\.dart$")
RECEIVER = re.compile(r"(api|client|http|axios|fetch|instance|dio|request|backend|rest)", re.I)

STR = r"""(?:'(?:\\.|[^'\\\n])*'|"(?:\\.|[^"\\\n])*"|`(?:\\.|[^`\\])*`)"""
TS_CALL = re.compile(
    r"(?P<recv>[A-Za-z_$][\w$]*)\s*\??\.\s*(?P<m>get|post|put|patch|delete|GET|POST|PUT|PATCH|DELETE)"
    r"\s*(?:<[^()]*>)?\(\s*(?P<lit>" + STR + ")"
)
# RTK Query style: `url: '/x'`, `query: (a) => '/x'`, `fetchAllPages(baseQuery, '/x'`.
TS_URL_KEY = re.compile(r"\b(?:url\s*:|query\s*:\s*\([^)]*\)\s*=>\s*\(?|fetchAllPages\s*(?:<[^()]*>)?\([^,]*,)\s*(?P<lit>" + STR + ")")
FETCH_CALL = re.compile(r"\bfetch\s*\(\s*(?P<lit>" + STR + ")")
DART_CALL = re.compile(
    r"\.(?P<m>get|post|put|patch|delete)\s*(?:<[^()]*>)?\(\s*(?P<lit>'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\")"
)
DART_CONST_CALL = re.compile(
    r"\.(?P<m>get|post|put|patch|delete)\s*(?:<[^()]*>)?\(\s*[A-Z]\w*\.(?P<name>\w+)"
)
ANY_STR = re.compile(STR)
DART_STR = re.compile(r"'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"")
CALL_TOOL = re.compile(r"callTool\s*(?:<[^()]*>)?\(\s*(?P<lit>" + STR + ")")
DART_CONST = re.compile(
    r"static\s+(?:const\s+|final\s+)?(?:String\s+)?(?P<name>\w+)\s*(?:\([^)]*\)\s*=>|=)\s*"
    r"(?P<lit>'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\")",
    re.S,
)
TS_BASE_PREFIX = re.compile(r"^\$\{[^}]*api[^}]*\}(?P<rest>/.*)$", re.I)
# Root routes that OpenAPI does not describe.
ROOT_ROUTES = {"/health", "/openapi.json", "/openapi.yaml", "/docs", "/redoc"}


@dataclass(frozen=True)
class Literal:
    file: str
    line: int
    method: str | None
    raw: str
    path: str
    query_keys: tuple[str, ...] = ()
    kind: str = "path"


@dataclass
class Finding:
    repo: str
    lit: Literal
    problem: str


@dataclass
class Spec:
    ops: dict[str, dict[str, set[str]]] = field(default_factory=dict)  # norm path -> method -> query keys
    raw: dict[str, str] = field(default_factory=dict)  # norm path -> openapi path


def split_segments(path: str) -> list[str]:
    return [s for s in path.split("/") if s]


def normalize(path: str) -> str:
    """Strip host, prefix, query, trailing slash. Turn every parameter into {}."""
    path = re.sub(r"^https?://[^/]+", "", path)
    path = path.split("#", 1)[0].split("?", 1)[0]
    if path.startswith(API_PREFIX):
        path = path[len(API_PREFIX):]
    path = re.sub(r"\$\{[^}]*\}|\$[A-Za-z_]\w*|\{[^}]*\}", "{}", path)
    segs = []
    for seg in split_segments(path):
        segs.append("{}" if seg.startswith(":") else seg)
    return "/" + "/".join(segs)


def _seg_match(a: str, b: str) -> bool:
    if a == b or a == "{}" or b == "{}":
        return True
    for x, y in ((a, b), (b, a)):
        if "{}" in x:
            rx = "^" + "[^/]+".join(re.escape(p) for p in x.split("{}")) + "$"
            if re.match(rx, y):
                return True
    return False


def path_match(lit: list[str], spec: list[str], *, prefix: bool = False) -> bool:
    if prefix:
        if len(lit) >= len(spec):
            return False
    elif len(lit) != len(spec):
        return False
    return all(_seg_match(a, b) for a, b in zip(lit, spec, strict=False))


def load_spec(path: Path) -> Spec:
    doc = json.loads(path.read_text(encoding="utf-8"))
    spec = Spec()
    for raw, item in doc["paths"].items():
        norm = normalize(raw)
        shared = _query_names(item.get("parameters", []), doc)
        methods = spec.ops.setdefault(norm, {})
        spec.raw[norm] = raw
        for method, op in item.items():
            if method in METHODS:
                methods[method] = shared | _query_names(op.get("parameters", []), doc)
    return spec


def _query_names(params: list[dict], doc: dict) -> set[str]:
    names: set[str] = set()
    for p in params:
        if "$ref" in p:
            node = doc
            for part in p["$ref"].lstrip("#/").split("/"):
                node = node[part]
            p = node
        if p.get("in") == "query":
            names.add(p["name"])
    return names


# ------------------------------------------------------------------ extraction


def _unquote(lit: str) -> str:
    return lit[1:-1]


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _url_query_keys(raw: str) -> tuple[str, ...]:
    if "?" not in raw:
        return ()
    query = raw.split("?", 1)[1].split("#", 1)[0]
    keys = []
    for part in re.split(r"&", query):
        key = re.split(r"=", part, maxsplit=1)[0]
        if re.fullmatch(r"[A-Za-z_][\w.\[\]-]*", key):
            keys.append(key)
    return tuple(keys)


def _balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Index of the bracket that closes the one at start, or -1."""
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _object_keys(body: str) -> tuple[str, ...] | None:
    """Top-level keys of an object literal body. None when a spread hides keys."""
    items, depth, quote, cur = [], 0, None, []
    i = 0
    while i < len(body):
        c = body[i]
        if quote:
            cur.append(c)
            if c == "\\":
                i += 1
                cur.append(body[i : i + 1])
            elif c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
            cur.append(c)
        elif c in "([{":
            depth += 1
            cur.append(c)
        elif c in ")]}":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            items.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    items.append("".join(cur))
    keys = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        if item.startswith("..."):
            return None
        m = re.match(r"""^(?:['"]([^'"]+)['"]|([A-Za-z_$][\w$]*))\s*(?::|$|\()""", item)
        if m:
            keys.append(m.group(1) or m.group(2))
    return tuple(keys)


def _call_query_keys(text: str, lit_start: int, lit_end: int) -> tuple[str, ...]:
    """Static query keys in the options object of the call whose first argument is the literal."""
    close = _balanced(text, text.rfind("(", 0, lit_start), "(", ")")
    args = text[lit_end : close if close != -1 else lit_end + 400]
    for marker in ("query", "params"):
        m = re.search(rf"\b{marker}\s*:\s*\{{", args)
        if not m:
            continue
        end = _balanced(args, m.end() - 1, "{", "}")
        keys = _object_keys(args[m.end() : end]) if end != -1 else None
        if keys is None or {"query", "path", "header"} & set(keys):
            continue  # a spread hides keys, or this is the openapi-fetch wrapper
        return keys
    return ()


def _enclosing_object(text: str, pos: int) -> str:
    """Text of the innermost {...} that contains pos, or an empty string."""
    depth, i = 0, pos - 1
    while i >= 0:
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            if depth == 0:
                end = _balanced(text, i, "{", "}")
                return text[i : end + 1] if end != -1 else ""
            depth -= 1
        i -= 1
    return ""


def has_generated_types(repo: Path) -> bool:
    pkg = repo / "package.json"
    if pkg.exists() and re.search(r"openapi-(typescript|fetch)", pkg.read_text(encoding="utf-8")):
        return True
    if (repo / "openapi" / "openapi.json").exists():
        return True
    return any(repo.glob("src/**/generated")) or any(repo.glob("src/**/*.gen.ts"))


def iter_sources(repo: Path):
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or path.suffix not in SOURCE_SUFFIXES or SKIP_FILE.search(path.name):
            continue
        rel = path.relative_to(repo)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]) and not DART_PATH_FILE.search(path.name):
            continue
        yield path, rel


def _resolve_dart_consts(text: str) -> dict[str, str]:
    consts = {m["name"]: _unquote(m["lit"]) for m in DART_CONST.finditer(text)}
    for _ in range(5):
        for name, val in consts.items():
            consts[name] = re.sub(
                r"\$\{(\w+)(?:\([^)]*\))?\}|\$(\w+)",
                lambda m: consts.get(m.group(1) or m.group(2), m.group(0)),
                val,
            )
    return consts


def extract(repo: Path, *, query_objects: bool | None = None) -> tuple[list[Literal], list[Literal]]:
    """Return (path literals, callTool literals) for one repo."""
    if query_objects is None:
        query_objects = has_generated_types(repo)
    paths: list[Literal] = []
    tools: list[Literal] = []
    sources = list(iter_sources(repo))
    consts: dict[str, str] = {}
    for path, _ in sources:
        if DART_PATH_FILE.search(path.name):
            consts.update(_resolve_dart_consts(path.read_text(encoding="utf-8", errors="replace")))
    for path, rel in sources:
        text = re.sub(r"^[ \t]*//.*$", "", path.read_text(encoding="utf-8", errors="replace"), flags=re.M)
        name = str(rel)
        for m in CALL_TOOL.finditer(text):
            tools.append(Literal(name, _line_of(text, m.start()), None, _unquote(m["lit"]), _unquote(m["lit"]), kind="tool"))
        if path.suffix == ".dart":
            paths.extend(_extract_dart(text, name, bool(DART_PATH_FILE.search(path.name)), consts))
        else:
            paths.extend(_extract_ts(text, name, query_objects))
    return paths, tools


def _add(out: list[Literal], seen: set, file: str, line: int, method: str | None, raw: str, keys: tuple[str, ...]):
    norm = normalize(raw)
    if raw.startswith("http") and API_PREFIX not in raw:
        return
    if not raw.startswith(("/", "http")) and not raw.startswith("${") or norm == "/" or norm.startswith("/{}"):
        return
    key = (line, method, raw)
    if key in seen:
        return
    seen.add(key)
    out.append(Literal(file, line, method, raw, norm, tuple(dict.fromkeys(keys + _url_query_keys(raw)))))


def _extract_ts(text: str, file: str, query_objects: bool) -> list[Literal]:
    out: list[Literal] = []
    seen: set = set()
    consumed: set[int] = set()
    for m in TS_CALL.finditer(text):
        if not RECEIVER.search(m["recv"]):
            continue
        raw = _unquote(m["lit"])
        base = TS_BASE_PREFIX.match(raw)
        raw = base["rest"] if base else raw
        if not raw.startswith(("/", "http")):
            continue
        keys = _call_query_keys(text, m.start("lit"), m.end("lit")) if query_objects else ()
        consumed.add(m.start("lit"))
        _add(out, seen, file, _line_of(text, m.start("lit")), m["m"].lower(), raw, keys)
    for m in TS_URL_KEY.finditer(text):
        raw = _unquote(m["lit"])
        base = TS_BASE_PREFIX.match(raw)
        raw = base["rest"] if base else raw
        if not raw.startswith(("/", "http")):
            continue
        obj = _enclosing_object(text, m.start("lit"))
        meth = re.search(r"\bmethod\s*:\s*['\"](\w+)['\"]", obj)
        keys: tuple[str, ...] = ()
        pm = re.search(r"\bparams\s*:\s*\{", obj) if query_objects else None
        if pm:
            end = _balanced(obj, pm.end() - 1, "{", "}")
            keys = _object_keys(obj[pm.end() : end]) or () if end != -1 else ()
        consumed.add(m.start("lit"))
        _add(out, seen, file, _line_of(text, m.start("lit")), meth[1].lower() if meth else "get", raw, keys)
    for m in FETCH_CALL.finditer(text):
        raw = _unquote(m["lit"])
        base = TS_BASE_PREFIX.match(raw)
        raw = base["rest"] if base else raw
        if not (base or raw.startswith(("/api/v1", "http"))):
            continue
        meth = re.search(r"method\s*:\s*['\"](\w+)['\"]", text[m.end() : m.end() + 300])
        consumed.add(m.start("lit"))
        _add(out, seen, file, _line_of(text, m.start("lit")), meth[1].lower() if meth else "get", raw, ())
    for m in ANY_STR.finditer(text):
        if m.start() in consumed:
            continue
        raw = _unquote(m.group())
        base = TS_BASE_PREFIX.match(raw)
        if base:
            raw = base["rest"]
        elif not raw.startswith(API_PREFIX + "/"):
            continue
        _add(out, seen, file, _line_of(text, m.start()), None, raw, ())
    return out


def _extract_dart(text: str, file: str, is_path_file: bool, repo_consts: dict[str, str]) -> list[Literal]:
    out: list[Literal] = []
    seen: set = set()
    consts = _resolve_dart_consts(text) if is_path_file else {}
    resolved = {}  # position of a literal -> resolved raw
    for m in DART_CALL.finditer(text):
        raw = _unquote(m["lit"])
        if raw.startswith("/") or raw.startswith("http"):
            resolved[m.start("lit")] = (m["m"], raw)
    # `_dio.get(ApiPaths.name(...))`: the constant gives the path, the call gives the method.
    for m in DART_CONST_CALL.finditer(text):
        raw = repo_consts.get(m["name"])
        if raw and raw.startswith("/"):
            resolved[m.start("name")] = (m["m"], raw)
    for pos, (method, raw) in resolved.items():
        _add(out, seen, file, _line_of(text, pos), method, raw, ())
    for m in DART_STR.finditer(text):
        if m.start() in resolved:
            continue
        raw = _unquote(m.group())
        if is_path_file and raw.startswith("/"):
            for _ in range(5):
                raw = re.sub(
                    r"\$\{(\w+)(?:\([^)]*\))?\}|\$(\w+)",
                    lambda mm: consts.get(mm.group(1) or mm.group(2), mm.group(0)),
                    raw,
                )
            _add(out, seen, file, _line_of(text, m.start()), None, raw, ())
        elif raw.startswith(API_PREFIX + "/"):
            _add(out, seen, file, _line_of(text, m.start()), None, raw, ())
    return out


# ------------------------------------------------------------------ checking


def check_literal(lit: Literal, spec: Spec) -> str | None:
    if lit.path in ROOT_ROUTES:
        return None
    segs = split_segments(lit.path)
    hits = [p for p in spec.ops if path_match(segs, split_segments(p))]
    if not hits:
        if any(path_match(segs, split_segments(p), prefix=True) for p in spec.ops):
            return None  # fragment of a longer route
        return "no such path in docs/openapi.json"
    if lit.method:
        ops = [spec.ops[p][lit.method] for p in hits if lit.method in spec.ops[p]]
        if not ops:
            allowed = sorted({m for p in hits for m in spec.ops[p]})
            return f"path exists ({spec.raw[hits[0]]}) but not with {lit.method.upper()}; allowed: {', '.join(m.upper() for m in allowed)}"
        declared = set().union(*ops)
    else:
        declared = set().union(*(q for p in hits for q in spec.ops[p].values()))
    extra = [k for k in lit.query_keys if k not in declared]
    if extra:
        return f"query key not declared by the operation: {', '.join(extra)}"
    return None


def check_repo(repo: Path, spec: Spec, tool_names: set[str]) -> tuple[list[Finding], int]:
    paths, tools = extract(repo)
    findings = [Finding(repo.name, lit, problem) for lit in paths if (problem := check_literal(lit, spec))]
    findings += [
        Finding(repo.name, lit, "callTool name is not a registered MCP tool")
        for lit in tools
        if lit.path not in tool_names
    ]
    return findings, len(paths) + len(tools)


def render(repos: list[Path], results: dict[str, list[Finding]], counts: dict[str, int]) -> str:
    lines = []
    for repo in repos:
        found = results[str(repo)]
        lines.append(f"## {repo}")
        lines.append(f"Literals checked: {counts[str(repo)]}. Findings: {len(found)}.")
        lines.append("")
        for f in found:
            method = (f.lit.method or "any").upper()
            lines.append(f"- {f.lit.file}:{f.lit.line} {method} {f.lit.raw}: {f.problem}")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repos", nargs="+", type=Path)
    ap.add_argument("--openapi", type=Path, default=DEFAULT_OPENAPI)
    ap.add_argument("--tool-names", type=Path, default=DEFAULT_TOOL_NAMES)
    args = ap.parse_args(argv)

    spec = load_spec(args.openapi)
    tool_names = set(json.loads(args.tool_names.read_text(encoding="utf-8"))) if args.tool_names.exists() else set()
    results: dict[str, list[Finding]] = {}
    counts: dict[str, int] = {}
    for repo in args.repos:
        repo = repo.resolve()
        results[str(repo)], counts[str(repo)] = check_repo(repo, spec, tool_names)
    print(render([r.resolve() for r in args.repos], results, counts))
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
