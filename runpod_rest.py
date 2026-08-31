"""The three RunPod REST calls the Python SDK cannot make.

`runpod` 1.12 exposes `create_endpoint`, `create_template` and
`update_endpoint_template`, and that is the whole endpoint surface. Its mutation
generators (`runpod/api/mutations/endpoints.py`) confirm it: `saveEndpoint` and
`updateEndpointTemplate`, nothing else. So there is no way through the SDK to

  * delete an endpoint,
  * delete a template,
  * or set an endpoint's execution timeout.

Both scripts here needed one of those. `destroy.py` looked the delete up
defensively — `getattr(runpod, "delete_endpoint", None) or getattr(runpod.api,
...)` — so it did not crash. It printed "delete via dashboard" to stderr and
returned **0**, which is worse: a teardown that exits successfully having deleted
nothing is one a CI job believes, while the endpoint keeps billing. It also
printed "Scaling endpoint to 0 workers and deleting" without scaling anything.

`deploy.py` could only report the execution timeout, because `create_endpoint`
takes no such parameter. `executionTimeoutMs` is a REST field, so it can be
applied instead.

The REST API has all three. Deliberately `urllib` rather than httpx or requests:
this is operator-side tooling installed with `pip install -e ".[deploy]"`, whose
only declared dependency is python-dotenv, and three HTTP calls do not justify
widening that.

  https://docs.runpod.io/api-reference/endpoints/DELETE/endpoints/endpointId
  https://docs.runpod.io/api-reference/endpoints/PATCH/endpoints/endpointId
  https://docs.runpod.io/api-reference/templates/DELETE/templates/templateId
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

BASE_URL = "https://rest.runpod.io/v1"

# PATCH returns the updated object, DELETE returns no content. Both are success.
_OK = (200, 204)


class RunpodApiError(RuntimeError):
    """A REST call did not return a success status.

    ``status`` is the HTTP status when there was a response, and None when the
    call never got one -- DNS, connect, timeout. A caller that needs to tell
    "already gone" from "may still be running" reads this; the status is in the
    message too, but a message is not a contract.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def call(
    method: str,
    path: str,
    *,
    api_key: str,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any] | None:
    """One REST call. Returns the decoded body, or None for a 204.

    Raises RunpodApiError with the response text on any non-success status, so a
    caller does not have to distinguish "worked" from "returned a 4xx body" —
    which is exactly the distinction the old SDK calls silently lost.
    """
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 — BASE_URL is a fixed https host
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            status = response.status
            payload = response.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RunpodApiError(
            f"{method} {path} returned {e.code}: {detail}", status=e.code
        ) from e
    except urllib.error.URLError as e:
        raise RunpodApiError(f"{method} {path} could not reach RunPod: {e.reason}") from e
    except (TimeoutError, OSError) as e:
        # urllib raises TimeoutError directly when the stall is in the response
        # headers or body rather than the connect, so it arrives unwrapped and
        # missed both handlers above. In deploy.py that lands *after*
        # create_endpoint has succeeded, and main() catches only RunpodApiError
        # — so the script died on a traceback before printing the id of an
        # endpoint that now exists and bills. URLError is itself an OSError, so
        # this has to come last to stay reachable.
        raise RunpodApiError(f"{method} {path} failed: {type(e).__name__}: {e}") from e

    if status not in _OK:
        raise RunpodApiError(f"{method} {path} returned {status}", status=status)
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        # A success status with an unparseable body is still a success; the
        # callers here act on the status, not on the contents.
        return None


def scale_to_zero(endpoint_id: str, *, api_key: str) -> None:
    """Set both worker bounds to zero.

    RunPod's own GraphQL documentation states an endpoint's min and max workers
    must both be zero before it can be deleted. Whether the REST delete enforces
    the same precondition is not documented, so this runs first either way — it
    is idempotent and costs one call.
    """
    call(
        "PATCH",
        f"/endpoints/{endpoint_id}",
        api_key=api_key,
        body={"workersMin": 0, "workersMax": 0},
    )


def set_execution_timeout(endpoint_id: str, *, seconds: int, api_key: str) -> None:
    """Set the per-job hard timeout, in seconds.

    `executionTimeoutMs` is an EndpointUpdateInput field. It has no equivalent on
    the SDK's create call, which is why this is a second step after creation
    rather than part of it.
    """
    call(
        "PATCH",
        f"/endpoints/{endpoint_id}",
        api_key=api_key,
        body={"executionTimeoutMs": seconds * 1000},
    )


def delete_endpoint(endpoint_id: str, *, api_key: str) -> None:
    call("DELETE", f"/endpoints/{endpoint_id}", api_key=api_key)


def delete_template(template_id: str, *, api_key: str) -> None:
    call("DELETE", f"/templates/{template_id}", api_key=api_key)
