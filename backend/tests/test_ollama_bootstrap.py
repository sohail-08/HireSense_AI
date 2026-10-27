"""Offline bootstrap tests: no model downloads, paid APIs or candidate records."""
import io
import json
from pathlib import Path
import urllib.error

import pytest
import yaml

from app import bootstrap_ollama as bootstrap


def tags(digest=bootstrap.DEFAULT_DIGEST):
    return {"models": [{"name": bootstrap.DEFAULT_MODEL, "digest": digest}]}


class FakeAPI:
    def __init__(self, inventory=None, vector=None):
        self.inventory = tags() if inventory is None else inventory
        self.vector = [0.1] * 768 if vector is None else vector
        self.calls = []

    def __call__(self, base, path, payload=None, *, timeout):
        self.calls.append((path, payload, timeout))
        assert base == "http://ollama:11434"
        if path == "/api/tags":
            return self.inventory
        if path == "/api/pull":
            self.inventory = tags()
            return {"status": "success"}
        if path == "/api/embed":
            assert payload == {"model": bootstrap.DEFAULT_MODEL, "input": bootstrap.PROBE, "truncate": False}
            return {"embeddings": [self.vector]}
        raise AssertionError("Unexpected bootstrap request")


def test_empty_volume_downloads_model_then_checks_digest_dimensions_and_inference():
    api = FakeAPI({"models": []})
    result = bootstrap.ensure_model(request=api)
    assert result == {"status": "ready", "model": bootstrap.DEFAULT_MODEL,
        "digest": bootstrap.DEFAULT_DIGEST, "dimensions": 768, "reused_cache": False}
    assert [item[0] for item in api.calls] == ["/api/tags", "/api/pull", "/api/tags", "/api/embed", "/api/tags"]
    assert api.calls[1][1] == {"model": bootstrap.DEFAULT_MODEL, "stream": False}
    assert api.calls[1][2] == 1800


def test_cached_model_restarts_without_accessing_the_model_registry():
    api = FakeAPI()
    result = bootstrap.ensure_model(model="nomic-embed-text", request=api)
    assert result["reused_cache"]
    assert [item[0] for item in api.calls] == ["/api/tags", "/api/embed", "/api/tags"]


def test_digest_mismatch_does_not_replace_cache_or_accept_incompatible_vectors():
    api = FakeAPI(tags("a" * 64))
    with pytest.raises(bootstrap.SetupError, match="digest differs"):
        bootstrap.ensure_model(request=api)
    assert [item[0] for item in api.calls] == ["/api/tags"]


@pytest.mark.parametrize("vector", [[0.1] * 1024, [0.0] * 768, [float("nan")] * 768,
    [float("inf")] * 768, [True] * 768, ["0.1"] * 768, []])
def test_invalid_embeddings_never_mark_setup_successful(vector):
    with pytest.raises(bootstrap.SetupError, match="768-dimensional"):
        bootstrap.ensure_model(request=FakeAPI(vector=vector))


@pytest.mark.parametrize("inventory", [{}, {"models": None}, tags("invalid"), {"models": tags()["models"] * 2}])
def test_invalid_model_inventory_is_rejected(inventory):
    with pytest.raises(bootstrap.SetupError, match="invalid"):
        bootstrap.ensure_model(request=FakeAPI(inventory))


def test_model_change_during_probe_is_rejected():
    api = FakeAPI()
    def changing(base, path, payload=None, *, timeout):
        value = api(base, path, payload, timeout=timeout)
        if path == "/api/embed":
            api.inventory = tags("b" * 64)
        return value
    with pytest.raises(bootstrap.SetupError, match="changed during setup"):
        bootstrap.ensure_model(request=changing)


@pytest.mark.parametrize("result", [{"status": "downloading"}, {"error": "download failed"}])
def test_incomplete_pull_never_allows_backend_readiness(result):
    api = FakeAPI({"models": []})
    def incomplete(base, path, payload=None, *, timeout):
        return result if path == "/api/pull" else api(base, path, payload, timeout=timeout)
    with pytest.raises(bootstrap.SetupError, match="download did not finish"):
        bootstrap.ensure_model(request=incomplete)


@pytest.mark.parametrize("options", [{"base_url": "file:///tmp/ollama"}, {"base_url": "http://user:secret@ollama:11434"},
    {"base_url": "http://[invalid"}, {"model": "bad model"}, {"expected_digest": ""}])
def test_invalid_configuration_fails_before_any_network_request(options):
    api = FakeAPI()
    with pytest.raises(bootstrap.SetupError):
        bootstrap.ensure_model(request=api, **options)
    assert not api.calls


@pytest.mark.parametrize("failure", [urllib.error.HTTPError("http://ollama/api/pull", 500, "private details", {}, None),
    urllib.error.URLError("private details")])
def test_http_failures_are_actionable_without_echoing_response_bodies(monkeypatch, failure):
    def failed(*args, **kwargs):
        raise failure
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", failed)
    with pytest.raises(bootstrap.SetupError) as result:
        bootstrap.request_json("http://ollama", "/api/pull", {})
    assert "private details" not in str(result.value)


@pytest.mark.parametrize("response", [{"error": "private details"}, [], "not json"])
def test_malformed_or_error_api_responses_are_not_success(monkeypatch, response):
    payload = response if response == "not json" else json.dumps(response)
    monkeypatch.setattr(bootstrap.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(payload.encode()))
    with pytest.raises(bootstrap.SetupError):
        bootstrap.request_json("http://ollama", "/api/embed", {})


def test_cli_success_uses_only_embedding_configuration(monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("OLLAMA_EMBEDDING_MODEL", bootstrap.DEFAULT_MODEL)
    monkeypatch.setenv("OLLAMA_MODEL_DIGEST", bootstrap.DEFAULT_DIGEST)
    def ready(base, model, digest):
        assert (base, model, digest) == ("http://ollama:11434", bootstrap.DEFAULT_MODEL, bootstrap.DEFAULT_DIGEST)
        return {"status": "ready"}
    monkeypatch.setattr(bootstrap, "ensure_model", ready)
    assert bootstrap.main() == 0
    assert json.loads(capsys.readouterr().out) == {"status": "ready"}


def test_cli_failure_exits_nonzero_without_readiness(monkeypatch, capsys):
    def failed(*args):
        raise bootstrap.SetupError("Model is unavailable.")
    monkeypatch.setattr(bootstrap, "ensure_model", failed)
    assert bootstrap.main() == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "Ollama setup failed: Model is unavailable." in captured.err


@pytest.mark.skipif(not (Path(__file__).parents[2] / "docker-compose.yml").is_file(),
    reason="Compose source is not packaged in the runtime image")
def test_compose_uses_private_persistent_ollama_and_gates_backend_on_verified_model():
    root = Path(__file__).parents[2]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    ollama, init, backend = (services[name] for name in ("ollama", "ollama-init", "backend"))
    assert ollama["image"].startswith("ollama/ollama:0.40.11@sha256:")
    assert "ports" not in ollama and "profiles" not in ollama
    assert ollama["volumes"] == ["ollama_data:/root/.ollama"] and "ollama_data" in compose["volumes"]
    assert ollama["healthcheck"]["test"] == ["CMD", "ollama", "list"]
    assert init["entrypoint"] == ["python", "-m", "app.bootstrap_ollama"]
    assert init["build"] == {"context": "./backend", "dockerfile": "Dockerfile.ollama-init"}
    assert init["depends_on"]["ollama"]["condition"] == "service_healthy"
    assert backend["depends_on"]["ollama-init"]["condition"] == "service_completed_successfully"
    assert backend["environment"]["OLLAMA_BASE_URL"] == init["environment"]["OLLAMA_BASE_URL"] == "http://ollama:11434"
    assert backend["environment"]["OLLAMA_EMBEDDING_MODEL"] == init["environment"]["OLLAMA_EMBEDDING_MODEL"]
    assert set(init["environment"]) == {"OLLAMA_BASE_URL", "OLLAMA_EMBEDDING_MODEL", "OLLAMA_MODEL_DIGEST"}
    assert "volumes" not in init and "ports" not in init
