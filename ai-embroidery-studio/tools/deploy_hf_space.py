"""Publish the API to a Hugging Face Docker Space (run by .github/workflows/deploy-hf-space.yml).

Environment:
  HF_TOKEN (write token), HF_SPACE ("user/space-name"), WEB_ORIGIN (the website URL, for CORS)
  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, EMB_DATABASE_URL     -> Space variables / secrets
  ANTHROPIC_API_KEY (optional)                                    -> Space secret, enables AI
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
README = """---
title: Embroidery Studio API
emoji: 🧵
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---

Backend of AI Embroidery Studio (FastAPI + Ink/Stitch). Deployed automatically from GitHub; do not edit here.
"""


def need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"missing required setting: {name}")
    return value


def main() -> None:
    token, space = need("HF_TOKEN"), need("HF_SPACE")
    variables = {"SUPABASE_URL": need("SUPABASE_URL"), "EMB_CORS_ORIGINS": need("WEB_ORIGIN").rstrip("/")}
    secrets = {"SUPABASE_SERVICE_ROLE_KEY": need("SUPABASE_SERVICE_ROLE_KEY"),
               "EMB_DATABASE_URL": need("EMB_DATABASE_URL")}
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        secrets["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"].strip()
        variables["EMB_AI_ENABLED"] = "1"
    else:
        variables["EMB_AI_ENABLED"] = "0"
    if not secrets["EMB_DATABASE_URL"].startswith("postgresql+psycopg://"):
        sys.exit("EMB_DATABASE_URL must start with postgresql+psycopg:// (see docs/DEPLOY_FREE.md)")

    api = HfApi(token=token)
    api.create_repo(space, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    for key, value in variables.items():
        api.add_space_variable(space, key, value)
    for key, value in secrets.items():
        api.add_space_secret(space, key, value)

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        for folder in ("services", "fixtures", "tools"):
            shutil.copytree(ROOT / folder, stage / folder,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "out", "data"))
        (stage / "infra/worker").mkdir(parents=True)
        shutil.copy(ROOT / "infra/worker/inkstitch-requirements.txt", stage / "infra/worker/")
        shutil.copy(ROOT / "infra/hf-space/Dockerfile", stage / "Dockerfile")
        (stage / "README.md").write_text(README, encoding="utf-8")
        api.upload_folder(repo_id=space, repo_type="space", folder_path=str(stage), delete_patterns="*",
                          commit_message=f"Deploy {os.environ.get('GITHUB_SHA', 'local')[:12]}")
    print(f"deployed: https://huggingface.co/spaces/{space}  API: https://{space.replace('/', '-').lower()}.hf.space")


if __name__ == "__main__":
    main()
