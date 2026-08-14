import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POSTMAN_DIR = ROOT / "tests" / "postman"
COLLECTION_PATH = POSTMAN_DIR / "SwimMate.postman_collection.json"
ENVIRONMENT_PATHS = (
    POSTMAN_DIR / "production.template.postman_environment.json",
    POSTMAN_DIR / "direct-api.template.postman_environment.json",
    POSTMAN_DIR / "local.template.postman_environment.json",
)
SECRET_KEYS = {"qa_username", "qa_password", "admin_id", "admin_pw"}


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fp:
        return json.load(fp)


def _requests(collection: dict):
    for folder in collection.get("item", []):
        for item in folder.get("item", []):
            request = item.get("request")
            if request:
                yield folder["name"], item["name"], request


def test_postman_collection_has_representative_ordered_flows():
    collection = _load_json(COLLECTION_PATH)

    assert collection["info"]["schema"].endswith("/v2.1.0/collection.json")
    folders = {folder["name"]: folder for folder in collection["item"]}
    assert list(folders) == [
        "00 Public & Anonymous",
        "10 User Training Data Loop",
        "20 Admin Read-only Boundary",
    ]

    user_flow = [item["name"] for item in folders["10 User Training Data Loop"]["item"]]
    assert user_flow.index("Create Smoke Training Log") < user_flow.index(
        "Monthly Report Reflects Same Log"
    )
    assert user_flow.index("Monthly Report Reflects Same Log") < user_flow.index(
        "Delete Smoke Training Log"
    )
    assert user_flow.index("Create Privacy-safe Monthly Result Card") < user_flow.index(
        "Revoke Monthly Result Card"
    )
    assert user_flow.index("Delete Smoke Training Log") < user_flow.index("User Logout")


def test_postman_requests_use_base_url_and_cover_required_boundaries(monkeypatch):
    collection = _load_json(COLLECTION_PATH)
    requests = list(_requests(collection))

    assert requests
    assert all(str(request["url"]).startswith("{{base_url}}/") for _, _, request in requests)

    method_urls = {(request["method"], request["url"].split("?", 1)[0]) for _, _, request in requests}
    assert {
        ("GET", "{{base_url}}/api/health"),
        ("POST", "{{base_url}}/auth/login"),
        ("GET", "{{base_url}}/auth/me"),
        ("POST", "{{base_url}}/api/training-log"),
        ("POST", "{{base_url}}/api/training-log/screenshot/confirm"),
        ("DELETE", "{{base_url}}/api/training-log/{{training_log_id}}"),
        ("GET", "{{base_url}}/api/report/monthly"),
        ("POST", "{{base_url}}/api/promotion/result-shares/monthly"),
        ("GET", "{{base_url}}/api/promotion/public/results/{{result_share_token}}"),
        ("DELETE", "{{base_url}}/api/promotion/result-shares/{{result_share_token}}"),
        ("GET", "{{base_url}}/api/account/insights"),
        ("GET", "{{base_url}}/api/admin/dashboard"),
        ("GET", "{{base_url}}/api/admin/users"),
        ("GET", "{{base_url}}/api/admin/logs"),
        ("POST", "{{base_url}}/auth/logout"),
    }.issubset(method_urls)

    sys.path.insert(0, str(ROOT / "api"))
    monkeypatch.chdir(ROOT / "tests")
    from main import app

    openapi_paths = app.openapi()["paths"]
    for method, raw_url in method_urls:
        path = raw_url.removeprefix("{{base_url}}")
        path = path.replace("{{training_log_id}}", "{log_id}")
        path = path.replace("{{result_share_token}}", "{token}")
        assert path in openapi_paths, f"Postman path is not registered: {path}"
        assert method.lower() in openapi_paths[path], f"Postman method is not registered: {method} {path}"


def test_postman_assets_never_store_credentials():
    collection = _load_json(COLLECTION_PATH)
    collection_values = {entry["key"]: entry.get("value") for entry in collection["variable"]}
    assert SECRET_KEYS.issubset(collection_values)
    assert all(collection_values[key] == "" for key in SECRET_KEYS)

    for path in ENVIRONMENT_PATHS:
        environment = _load_json(path)
        values = {entry["key"]: entry for entry in environment["values"]}
        assert SECRET_KEYS.issubset(values)
        for key in SECRET_KEYS:
            assert values[key]["value"] == ""
            assert values[key]["type"] == "secret"


def test_postman_smoke_is_mapped_to_unified_quality_gate_and_documentation():
    workflow = (ROOT / ".github" / "workflows" / "qa.yml").read_text(encoding="utf-8")
    quality_gate = (ROOT / "docs" / "QUALITY_GATE.md").read_text(encoding="utf-8")
    deployment = (ROOT / "docs" / "DEPLOYMENT.md").read_text(encoding="utf-8")
    postman_readme = (POSTMAN_DIR / "README.md").read_text(encoding="utf-8")

    assert "postman-smoke:" in workflow
    assert "tests/postman/SwimMate.postman_collection.json" in workflow
    assert "--environment /tmp/swimmate-postman-environment.json" in workflow
    assert "Remove ephemeral Postman environment" in workflow
    assert '--env-var "qa_password=' not in workflow
    assert "POSTMAN_API_KEY: 사용하지 않음" in postman_readme
    assert "Postman API 스모크" in quality_gate
    assert "Postman 27개 요청" in deployment
