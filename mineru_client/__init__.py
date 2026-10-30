"""mineru_client — thin Python wrappers around a deployed mineru-runpod endpoint.

Two clients, same endpoint:

- ``MineruClient`` — the native client. Full access to the worker's own request /
  response shape (inline markdown, volume_path, format filtering, every tier).
  Use this for new code.

    from mineru_client import MineruClient

    client = MineruClient(endpoint_id="...", api_key="...")
    result = client.parse_document(file_url="https://...", page_range="1-100")
    entry = MineruClient.first(result)            # one-element results list
    client.save_tarball(result, dest_dir="./out") # also accepts an entry

- ``MineruApiClient`` — a drop-in-shaped facade over the official MinerU cloud
  API (``mineru.net/api/v4/...``). Lets callers of that SaaS evaluate / migrate
  to a self-hosted RunPod endpoint with a near-identical code path.

    from mineru_client import MineruApiClient

    client = MineruApiClient(endpoint_id="...", api_key="...")
    task_id = client.create_task("https://...", model_version="vlm")["data"]["task_id"]
    done = client.wait_for_task(task_id)
    client.download_results(done, "./out")

Accepts PDF, images, Office and OpenDocument files, RTF, EPUB, OFD and HTML.
"""

from .api_compat import MineruApiClient
from .client import MineruClient, MineruClientError

__all__ = ["MineruClient", "MineruClientError", "MineruApiClient"]
