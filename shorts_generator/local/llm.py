"""Local LLM backend — calls OpenAI directly so no MuAPI account is needed."""
from ..config import OPENAI_BASE_URL, OPENAI_MODEL, require_openai_key


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local.

    Honors OPENAI_BASE_URL so any OpenAI-compatible gateway (9router, LiteLLM,
    Ollama's /v1, etc.) can serve the highlight-ranking LLM.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client_kwargs = {"api_key": require_openai_key()}
    if OPENAI_BASE_URL:
        client_kwargs["base_url"] = OPENAI_BASE_URL

    client = OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
