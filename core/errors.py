"""
One exception hierarchy and one place that turns any exception into a
sentence a person can act on.

The project previously had five error idioms at once: bare RuntimeError,
bare ValueError, `return jsonify({"error": str(e)}), 500` (which piped
raw exception text, absolute filesystem paths included, straight into the
browser), silent `except: pass`, and — in exactly one place, the job
runner — a genuinely good plain-English translation layer. That last one
was the right idea implemented once; this module promotes it into the
thing every error path goes through.

Two audiences, two fields, never mixed:
  - `user_message` is written for the person using the tool. It says what
    happened and what to do about it. It never contains a stack trace, a
    filesystem path, or a Python type name.
  - the exception's own str()/traceback is for the log.

`friendly_message(exc)` accepts ANY exception, not just ours, so a
requests.HTTPError raised deep inside a vendor SDK still surfaces as
"ElevenLabs is rate-limiting requests" rather than "HTTPError: 429".
"""

from __future__ import annotations


class PipelineError(Exception):
    """Base for every error this project raises deliberately.

    `user_message` defaults to str(self), so raising
    PipelineError("Pick a primary logo first.") already does the right
    thing — subclasses only override it when the technical message and
    the human one genuinely differ.
    """

    def __init__(self, message: str, *, user_message: str = None):
        super().__init__(message)
        self._user_message = user_message

    @property
    def user_message(self) -> str:
        return self._user_message or str(self)


class ConfigError(PipelineError):
    """A channel's configuration is missing or malformed. Raised at load
    time with the channel and field named, rather than surfacing as a
    KeyError several layers deep inside TTS, halfway through a render."""


class MissingCredentialError(PipelineError):
    """A required API key isn't set. Names the environment variable and
    what stops working without it."""

    def __init__(self, env_var: str, what_for: str):
        super().__init__(
            f"{env_var} is not set",
            user_message=(
                f"{env_var} isn't set in your environment, so {what_for} can't run. "
                f"Add it and restart."
            ),
        )
        self.env_var = env_var


class ExternalServiceError(PipelineError):
    """An outside service failed. `service` is the human name ("the voice
    service (ElevenLabs)"), not a hostname."""

    def __init__(self, service: str, message: str, *, user_message: str = None,
                 status: int = None):
        super().__init__(message, user_message=user_message)
        self.service = service
        self.status = status


class FootageLibraryError(PipelineError):
    """The footage library can't satisfy a request — empty, or missing
    files the database still references."""


class JobError(PipelineError):
    """A job can't be started, queued, or retried in its current state."""


# Maps a request URL fragment to the human name for that service. Used by
# _service_for_exception below to answer "which service actually failed"
# from a requests exception, since "an external service" alone isn't
# specific enough for anyone to act on.
_SERVICE_BY_URL_FRAGMENT = (
    ("elevenlabs", "The voice service (ElevenLabs)"),
    ("api.anthropic.com", "The AI service (Claude)"),
    ("api.openai.com", "The image service (OpenAI)"),
    ("pexels", "The stock footage service (Pexels)"),
    ("pixabay", "The stock footage service (Pixabay)"),
    ("bible-api", "The Bible verse service (bible-api.com)"),
    ("gutenberg", "Project Gutenberg"),
)


def _service_for_exception(exc: Exception) -> str:
    url = ""
    request = getattr(exc, "request", None)
    if request is not None:
        url = getattr(request, "url", "") or ""
    if not url:
        response = getattr(exc, "response", None)
        if response is not None:
            url = getattr(response, "url", "") or ""
    url = str(url).lower()
    for fragment, name in _SERVICE_BY_URL_FRAGMENT:
        if fragment in url:
            return name
    return "An external service"


def _http_message(exc, service: str) -> str:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 429:
        return (f"{service} is temporarily limiting how fast requests can be made. "
                f"This usually clears on its own within a few minutes — retrying should work.")
    if status in (401, 403):
        return (f"{service} rejected the request. Check that its API key is set correctly "
                f"and has the permissions it needs.")
    if status == 404:
        return f"{service} couldn't find what was requested. It may have moved or been removed."
    if status is not None and status >= 500:
        return (f"{service} is having problems on their end. Retrying should work "
                f"once it recovers.")
    return f"{service} rejected a request (HTTP {status})."


def friendly_message(exc: Exception) -> str:
    """A short, specific, plain-English description of any exception.

    Used by the web layer for every error a user sees and by the CLI when
    a run fails. The technical detail isn't discarded — callers keep the
    traceback alongside this — it's just kept out of the sentence someone
    has to read to find out whether their video got made.
    """
    if isinstance(exc, PipelineError):
        return exc.user_message

    # Imported lazily: core/ must stay importable without the pipeline's
    # heavier dependencies installed, and this is the only thing here
    # that needs requests.
    try:
        import requests
    except ImportError:
        requests = None

    if requests is not None:
        service = _service_for_exception(exc)
        if isinstance(exc, requests.exceptions.HTTPError):
            return _http_message(exc, service)
        if isinstance(exc, requests.exceptions.Timeout):
            return (f"{service} took too long to respond. It may be busy — "
                    f"retrying usually works.")
        if isinstance(exc, requests.exceptions.ConnectionError):
            return ("Couldn't reach an external service. Check your internet connection "
                    "and try again.")

    if isinstance(exc, FileNotFoundError):
        return ("A file this step needed is missing. The log below names which one.")
    if isinstance(exc, PermissionError):
        return ("A file couldn't be written — it may be open in another program. "
                "Close it and try again.")

    return ("Something went wrong while generating this video. The technical details "
            "are in the log below.")
