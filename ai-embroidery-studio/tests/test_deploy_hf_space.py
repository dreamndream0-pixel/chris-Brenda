"""tools/deploy_hf_space.py stages the right files and settings (HfApi faked)."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("deploy_hf_space", ROOT / "tools/deploy_hf_space.py")
    mod = importlib.util.module_from_spec(spec)
    pytest.importorskip("huggingface_hub")
    spec.loader.exec_module(mod)
    return mod


class FakeApi:
    calls = []

    def __init__(self, token):
        FakeApi.calls = [("token", token)]

    def create_repo(self, repo, **kw):
        FakeApi.calls.append(("create", repo, kw))

    def add_space_variable(self, repo, key, value):
        FakeApi.calls.append(("var", key, value))

    def add_space_secret(self, repo, key, value):
        FakeApi.calls.append(("secret", key, value))

    def upload_folder(self, repo_id, repo_type, folder_path, delete_patterns, commit_message):
        files = sorted(str(p.relative_to(folder_path)) for p in Path(folder_path).rglob("*") if p.is_file())
        FakeApi.calls.append(("upload", files, (Path(folder_path) / "README.md").read_text()))


ENV = {"HF_TOKEN": "hf_x", "HF_SPACE": "me/emb-api", "WEB_ORIGIN": "https://emb.vercel.app/",
       "SUPABASE_URL": "https://p.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_y",
       "EMB_DATABASE_URL": "postgresql+psycopg://u:p@h:6543/postgres", "ANTHROPIC_API_KEY": ""}


def test_stages_space(monkeypatch):
    mod = load()
    monkeypatch.setattr(mod, "HfApi", FakeApi)
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    mod.main()
    calls = FakeApi.calls
    create = next(c for c in calls if c[0] == "create")
    assert create[2]["space_sdk"] == "docker" and create[2]["private"] is False
    vars_ = {c[1]: c[2] for c in calls if c[0] == "var"}
    secrets = {c[1]: c[2] for c in calls if c[0] == "secret"}
    assert vars_ == {"SUPABASE_URL": "https://p.supabase.co", "EMB_CORS_ORIGINS": "https://emb.vercel.app",
                     "EMB_AI_ENABLED": "0"}
    assert set(secrets) == {"SUPABASE_SERVICE_ROLE_KEY", "EMB_DATABASE_URL"}  # no AI key -> not sent
    files, readme = next(c for c in calls if c[0] == "upload")[1:]
    assert "Dockerfile" in files and "services/api/main.py" in files and "infra/worker/inkstitch-requirements.txt" in files
    assert not any("__pycache__" in f or f.startswith("tests/") or f.startswith("apps/") for f in files)
    assert "sdk: docker" in readme and "app_port: 7860" in readme


def test_rejects_wrong_database_url(monkeypatch):
    mod = load()
    monkeypatch.setattr(mod, "HfApi", FakeApi)
    for k, v in {**ENV, "EMB_DATABASE_URL": "postgresql://u:p@h:6543/postgres"}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(SystemExit):
        mod.main()
