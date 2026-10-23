import os
import re
import time

from dotenv import find_dotenv, load_dotenv
from google import genai
from google.genai import types

load_dotenv(find_dotenv())

MODELS = ("gemini-3.8-flash", "gemini-3.5-flash-lite")
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
CLASSIFICATION_TIMEOUT_SECONDS = float(os.getenv("GEMINI_CLASSIFICATION_TIMEOUT", "45"))
CLASSIFICATION_POLL_INTERVAL_SECONDS = 2
GEMINI_REQUEST_TIMEOUT_SECONDS = 5.0

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


def get_rag_chain():
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY in .env before starting anomaly detection.")

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            # Reserve time for the fallback model within operate.sh's run window.
            timeout=25_000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    def classify(inputs):
        prompt = f"""LOG ENTRY TO ANALYZE:
{inputs['query']}

RELATED LOG SNIPPETS:
{inputs['context'] or '(No related entries yet; classify the log entry itself.)'}
"""
        for index, model in enumerate(MODELS):
            try:
                interaction = client.interactions.create(
                    model=model,
                    input=prompt,
                    system_instruction=SYSTEM_INSTRUCTIONS,
                    # Gemini requires stored interactions for background execution.
                    store=True,
                    generation_config={
                        "max_output_tokens": 500,
                        "thinking_level": "low",
                    },
                    background=True,
                    timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
                )
                print(
                    f"Gemini interaction {interaction.id} started with {model}.",
                    flush=True,
                )
                deadline = time.monotonic() + CLASSIFICATION_TIMEOUT_SECONDS
                last_wait_notice = time.monotonic()
                while interaction.status == "in_progress":
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        try:
                            client.interactions.cancel(
                                id=interaction.id,
                                timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
                            )
                        except Exception as cancel_error:
                            print(
                                f"Could not cancel timed-out Gemini interaction: {cancel_error}",
                                flush=True,
                            )
                        raise TimeoutError(
                            f"Gemini classification exceeded "
                            f"{CLASSIFICATION_TIMEOUT_SECONDS:g} seconds."
                        )
                    time.sleep(min(CLASSIFICATION_POLL_INTERVAL_SECONDS, remaining))
                    interaction = client.interactions.get(
                        id=interaction.id,
                        timeout=GEMINI_REQUEST_TIMEOUT_SECONDS,
                    )
                    now = time.monotonic()
                    if now - last_wait_notice >= 10:
                        print(
                            f"Gemini is still processing interaction {interaction.id} "
                            f"({int(now - (deadline - CLASSIFICATION_TIMEOUT_SECONDS))}s elapsed).",
                            flush=True,
                        )
                        last_wait_notice = now

                if interaction.status != "completed":
                    interaction_errors = getattr(interaction, "errors", None) or []
                    details = "; ".join(
                        f"{error.code or 'unknown'}: {error.message or 'no message'}"
                        for error in interaction_errors
                    )
                    raise RuntimeError(
                        f"Gemini interaction finished with status: {interaction.status}"
                        + (f" ({details})" if details else " (no error details returned)")
                    )
                if not interaction.output_text:
                    raise RuntimeError("Gemini completed without returning classification text.")
                print(f"Gemini classification completed with {model}.", flush=True)
                return interaction.output_text
            except Exception as exc:
                is_timeout = isinstance(exc, TimeoutError) or "timed out" in str(exc).lower()
                status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                if status is None:
                    match = re.search(r"\b(408|429|500|502|503|504)\b", str(exc))
                    status = int(match.group(1)) if match else None
                else:
                    try:
                        status = int(status)
                    except (TypeError, ValueError):
                        status = None
                error_text = str(exc).lower()
                retryable = status in RETRYABLE_STATUS_CODES or is_timeout or any(
                    marker in error_text
                    for marker in (
                        "resource_exhausted",
                        "rate limit",
                        "overloaded",
                        "temporarily unavailable",
                        "service unavailable",
                        "internal error",
                    )
                )
                if not retryable or index == len(MODELS) - 1:
                    raise
                if is_timeout:
                    reason = "request timed out"
                elif status is not None:
                    reason = f"HTTP {status}"
                else:
                    reason = next(
                        (
                            marker
                            for marker in (
                                "resource_exhausted",
                                "rate limit",
                                "overloaded",
                                "temporarily unavailable",
                                "service unavailable",
                                "internal error",
                            )
                            if marker in error_text
                        ),
                        "retryable server error",
                    )
                print(
                    f"Gemini {model} failed"
                    f" ({reason}); "
                    f"trying fallback {MODELS[index + 1]}.",
                    flush=True,
                )

        raise RuntimeError("No Gemini model was available for classification.")

    return classify
