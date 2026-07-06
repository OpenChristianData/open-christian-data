"""probe_models.py -- Query /v1/models on each free_llm_router provider.

Uses urllib only (no openai import) to avoid the inspect.py shadow bug
when run from the workspace root.
"""
import json
import os
import sys
import urllib.request
import urllib.error

PROVIDERS = [
    {
        "name": "cerebras",
        "url": "https://api.cerebras.ai/v1/models",
        "key_env": "CEREBRAS_API_KEY",
    },
    {
        "name": "nvidia",
        "url": "https://integrate.api.nvidia.com/v1/models",
        "key_env": "NVIDIA_API_KEY",
    },
    {
        "name": "mistral",
        "url": "https://api.mistral.ai/v1/models",
        "key_env": "MISTRAL_API_KEY",
    },
    {
        "name": "openrouter",
        "url": "https://openrouter.ai/api/v1/models",
        "key_env": "OPENROUTER_API_KEY",
    },
    {
        "name": "huggingface",
        "url": "https://router.huggingface.co/v1/models",
        "key_env": "HF_TOKEN",
    },
    {
        "name": "github",
        "url": "https://models.inference.ai.azure.com/v1/models",
        "key_env": "GITHUB_TOKEN",
    },
    {
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/models",
        "key_env": "GROQ_API_KEY",
    },
]


def probe(provider: dict) -> None:
    name = provider["name"]
    url = provider["url"]
    key_env = provider["key_env"]

    api_key = os.environ.get(key_env, "").strip("%")
    if not api_key:
        print(f"\n[{name}] SKIP -- {key_env} not set")
        return

    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"\n[{name}] HTTP {e.code} -- {body}")
        return
    except Exception as e:
        print(f"\n[{name}] ERROR -- {e}")
        return

    # OpenAI-compat: {"object":"list","data":[{"id":...},...]}}
    # Some providers return a plain list or different shape
    models = []
    if isinstance(data, dict):
        models = data.get("data", data.get("models", []))
    elif isinstance(data, list):
        models = data

    ids = sorted(
        m.get("id", m) if isinstance(m, dict) else str(m)
        for m in models
    )
    print(f"\n[{name}] {len(ids)} models:")
    for mid in ids:
        print(f"  {mid}")


if __name__ == "__main__":
    for p in PROVIDERS:
        probe(p)
    print("\nDone.")
