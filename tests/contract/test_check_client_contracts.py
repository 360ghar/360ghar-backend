"""The client contract extractor finds bad paths, methods, query keys and tool names."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_client_contracts import check_repo, load_spec

SPEC = {
    "paths": {
        "/api/v1/tours": {"get": {"parameters": [{"name": "limit", "in": "query"}]}, "post": {}},
        "/api/v1/tours/{tour_id}": {"get": {}, "patch": {}},
        "/api/v1/tours/{tour_id}/publish": {"post": {}},
    }
}


def _run(tmp_path: Path, files: dict[str, str]):
    spec_file = tmp_path / "openapi.json"
    spec_file.write_text(json.dumps(SPEC))
    repo = tmp_path / "repo"
    for name, body in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(body)
    findings, _ = check_repo(repo, load_spec(spec_file), {"visits_list"})
    return [(f.lit.file, f.lit.method, f.lit.path, f.problem.split(":")[0]) for f in findings]


def test_ts_clients(tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "package.json").write_text('{"dependencies": {"openapi-fetch": "1"}}')
    found = _run(
        tmp_path,
        {
            "src/a.ts": (
                "api.GET('/api/v1/tours', { params: { query: { limit: 1, bogus: 2 } } });\n"
                "api.PATCH('/api/v1/tours/{tour_id}', {});\n"
                "api.DELETE('/api/v1/tours/{tour_id}', {});\n"
                "http.get(`/tours/${id}/publish`);\n"
                "http.post(`/tours/${id}/publish`);\n"
                "fetch(`${API_BASE_URL}/nope/${id}`);\n"
                "map.get('/not/a/client');\n"
                "callTool('visits_list'); callTool('visits.cancel');\n"
            ),
            "src/generated/x.ts": "api.GET('/api/v1/ignored');",
            "src/a.test.ts": "api.GET('/api/v1/ignored');",
        },
    )
    problems = {(m, p): why for _, m, p, why in found}
    assert "query key not declared" in problems[("get", "/tours")]
    assert "not with DELETE" in problems[("delete", "/tours/{}")]
    assert "not with GET" in problems[("get", "/tours/{}/publish")]
    assert "no such path" in problems[("get", "/nope/{}")]
    assert (None, "visits.cancel") in problems
    assert len(found) == 5


def test_dart_clients(tmp_path):
    found = _run(
        tmp_path,
        {
            "lib/api_paths.dart": (
                "abstract final class ApiPaths {\n"
                "  static const tours = '/tours';\n"
                "  static String tour(int id) => '$tours/$id';\n"
                "  static String publish(int id) => '${tour(id)}/publish';\n"
                "  static const bad = '/tourz';\n"
                "}\n"
            ),
            "lib/repo.dart": (
                "final a = _dio.get<dynamic>(\n  '/tours/$id?cursor=1&limit=2');\n"
                "final b = _dio.put(ApiPaths.tour(id));\n"
                "final c = _dio.post(ApiPaths.publish(id));\n"
            ),
        },
    )
    problems = {(f, m, p): why for f, m, p, why in found}
    assert "query key not declared" in problems[("lib/repo.dart", "get", "/tours/{}")]
    assert "not with PUT" in problems[("lib/repo.dart", "put", "/tours/{}")]
    assert ("lib/api_paths.dart", None, "/tourz") in problems
    assert len(found) == 3
