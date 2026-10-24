"""Provider-specific log classifiers used by the analysis worker pool."""
import os
from dotenv import find_dotenv, load_dotenv
from google import genai
from google.genai import types

load_dotenv(find_dotenv())

SYSTEM_INSTRUCTIONS = """
You are a Site Reliability / Systems Assistant. Classify the supplied live log
entry itself, using retrieved log snippets as supporting context.

Detect whether the entry indicates an anomaly. If it does, identify the error
type, suggest a fix, and provide useful commands. Treat clear failures,
timeouts, connection errors, and critical conditions as anomalies unless the
entry shows they were expected or recovered.

Return only a JSON object with these keys:
- anomaly_detected (true or false)
- error_type (string or "none")
- suggested_fix (string or "none")
- commands (list of strings or [])
- explanation (short reasoning)
- confidence (low, medium, or high)
"""


def _prompt(inputs):
    return f"""LOG ENTRY TO ANALYZE:
{inputs['query']}

RELATED LOG SNIPPETS:
{inputs['context'] or '(No related entries yet; classify the log entry itself.)'}
"""


def get_analyzers():
    """Return configured model workers as {worker_name: (model_id, callable)}.

    Configure ANALYSIS_WORKERS as comma-separated provider/model pairs, for
    example: gemini:gemini-3.8-flash,groq:qwen/qwen3.8-27b.
    """
    configured = os.getenv(
        "ANALYSIS_WORKERS",
        "gemini:gemini-3.8-flash,groq:qwen/qwen3.8-27b",
    )
    workers = {}
    for item in configured.split(","):
        item = item.strip()
        if not item:
            continue
        provider, separator, model = item.partition(":")
        if not separator or not model.strip():
            raise ValueError(f"Invalid ANALYSIS_WORKERS entry: {item!r}")
        provider, model = provider.strip().lower(), model.strip()
        worker_name = f"{provider}:{model}"

        if provider == "gemini":
            api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("Set GOOGLE_API_KEY to enable the Gemini analysis worker.")
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=60_000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )

            def classify_gemini(inputs, client=client, model=model):
                result = client.models.generate_content(
                    model=model,
                    contents=_prompt(inputs),
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_INSTRUCTIONS,
                        response_mime_type="application/json",
                        max_output_tokens=500,
                    ),
                )
                if not result.text:
                    raise RuntimeError("Gemini completed without returning classification text.")
                return result.text

            workers[worker_name] = (model, classify_gemini)
        elif provider == "groq":
            api_key = os.getenv("GROQ_API_KEY")
            if not api_key:
                raise RuntimeError("Set GROQ_API_KEY to enable the Groq analysis worker.")
            from groq import Groq

            client = Groq(api_key=api_key, timeout=60.0, max_retries=0)

            def classify_groq(inputs, client=client, model=model):
                result = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                        {"role": "user", "content": _prompt(inputs)},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_completion_tokens=500,
                )
                content = result.choices[0].message.content
                if not content:
                    raise RuntimeError("Groq completed without returning classification text.")
                return content

            workers[worker_name] = (model, classify_groq)
        else:
            raise ValueError(f"Unsupported analysis provider {provider!r}; use gemini or groq.")

    if not workers:
        raise RuntimeError("ANALYSIS_WORKERS must configure at least one model worker.")
    return workers
