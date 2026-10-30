# mineru-runpod

<!-- badges: ci, license, python, runpod -->
[![CI](https://github.com/sergeyshmakov/mineru-runpod/actions/workflows/ci.yml/badge.svg)](https://github.com/sergeyshmakov/mineru-runpod/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![MinerU](https://img.shields.io/badge/MinerU-4.1-purple)](https://github.com/opendatalab/MinerU)
[![Runpod](https://api.runpod.io/badge/sergeyshmakov/mineru-runpod)](https://console.runpod.io/hub/sergeyshmakov/mineru-runpod)
[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-fa6673.svg)](https://www.conventionalcommits.org/)

Serverless [MinerU](https://github.com/opendatalab/MinerU) document parser on [RunPod](https://runpod.io?ref=31jdfpnq). MinerU 4.1.x runtime, with its small models and the `MinerU2.5-Pro-2605-1.2B` VLM baked into the image. Scales to zero.

<!-- MEASURE: warm $/page on the 2.x default tier (standard) on a 24 GB serverless RTX 4090, before a per-page price goes back into the line above -->

[Docs](https://mineru.shmakov.tools/) · [Get started on RunPod](https://runpod.io?ref=31jdfpnq) · [Upgrading to 2.x](https://mineru.shmakov.tools/getting-started/upgrade-to-2/) · [Blog](https://mineru.shmakov.tools/blog/)

> ⚠️ **Not an official MinerU project.** This is an independent wrapper that packages the open-source MinerU runtime as a RunPod Serverless worker. It is not affiliated with, endorsed by, or supported by OpenDataLab, who publish MinerU, or by RunPod.

## What this is

A port of official MinerU to RunPod Serverless, not a variant of it. The worker exposes what upstream MinerU exposes, under upstream's names (its quality tiers, `ocr_mode`, `page_range`, its output files and renders), and adds no engine behaviour: no parsing modes, models or language packs of its own, and when MinerU drops a capability, this template drops it too. What it adds is what RunPod needs around MinerU: a job contract, input fetching, output transport and scale-to-zero. So parsing quality is MinerU's to answer: report it [upstream](https://github.com/opendatalab/MinerU/issues), and anything about this worker [here](https://github.com/sergeyshmakov/mineru-runpod/issues).

> **Upgrading from 1.x?** 2.0 moves to MinerU 4.1: `backend` became `tier`, `start_page`/`end_page` became a 1-based `page_range`, and `lang` is gone along with MinerU's per-language OCR. Payloads that still send the old fields fail validation. [Upgrading to 2.x](https://mineru.shmakov.tools/getting-started/upgrade-to-2/) maps each one; to stay on MinerU 3.4, pin the `v1.13.0` release.

## Parse a document

**Python (`mineru_client`):**

```python
from mineru_client import MineruClient

client = MineruClient(endpoint_id="<your-endpoint-id>")
result = client.parse_document(file_url="https://example.com/report.pdf", page_range="1-5")
client.save_tarball(result, "./out/doc")
# → doc.md + content lists + middle.json + structured content + images/
```

**curl (no SDK):**

```sh
curl -X POST "https://api.runpod.ai/v2/<endpoint-id>/runsync" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"file_url":"https://example.com/report.pdf","page_range":"1-5","transport":"inline"}}'
```

The response wraps each parsed file as an entry inside `results: [...]`. For a single document, the markdown sits at `output.results[0].markdown` — pipe it straight to a file: `curl ... | jq -r '.output.results[0].markdown' > report.md`.

Accepts PDFs and images (PNG, JPEG, WebP, GIF, BMP, TIFF, JPEG 2000), which run at the tier you pick, plus Office files (DOC/DOCX, PPT/PPTX, XLS/XLSX), OpenDocument, RTF, EPUB, OFD, HTML and CSV/TSV, which MinerU parses natively — see [Input formats](https://mineru.shmakov.tools/guides/input-formats/). Two orthogonal knobs control output — **transport** (`tarball_b64` / `inline` / `s3`) and **formats**, which can also ask for MinerU's HTML, LaTeX, DOCX, EPUB and PDF renders — both covered in [Output modes](https://mineru.shmakov.tools/guides/output-modes/).

## Why this exists

- **MinerU** produces structured Markdown/JSON for text, charts, tables, and math, at four quality tiers: from `flash`, its fastest pass over the PDF's own text layer, to `advanced`, where the 1.2B VLM reads layout and content itself. See the [paper](https://arxiv.org/abs/2604.04771), [repo](https://github.com/opendatalab/MinerU), and [model card](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B) for the published evaluation scope.
- **RunPod Serverless** bills per-second and scales to zero, so you pay for GPU time while documents parse instead of for an always-on GPU. See [RunPod pricing](https://www.runpod.io/pricing) for current rates.
  <!-- MEASURE: cost of a 100-page document on the 2.x default tier (standard) on a 24 GB serverless RTX 4090 -->
- Wiring the two together is the part this repo does for you. Deploy from the [RunPod Hub](https://runpod.io?ref=31jdfpnq) in one click, or fork the repo for full control.

## Calling the endpoint

### A. Quick start with `MineruClient`

A small Python wrapper that lives in this repo. Best for prototyping and single-user scripts — usage is the snippet above. Install it with:

```powershell
# pip
pip install "mineru-client @ git+https://github.com/sergeyshmakov/mineru-runpod"

# or uv
uv pip install "mineru-client @ git+https://github.com/sergeyshmakov/mineru-runpod"
```

### B. Production with RunPod SDK / HTTP

For high-throughput, async, or non-Python callers. Hit the endpoint directly using the documented [JSON payload contract](https://mineru.shmakov.tools/reference/api/).

```python
import runpod
runpod.api_key = "..."
endpoint = runpod.Endpoint("<endpoint-id>")
result = endpoint.run_sync({"input": {"file_url": "https://example.com/report.pdf"}})
```

### C. Migrating from the official MinerU API

Already calling the MinerU cloud API (`mineru.net/api/v4/...`)? `MineruApiClient` mirrors its `create_task` / `get_task` surface over your own endpoint, so you can evaluate or migrate with a near-identical code path. See [Migrate from the MinerU API](https://mineru.shmakov.tools/getting-started/migrate-from-mineru-api/).

Prototype with A; switch to B once you need async, retries, or multi-language callers. See [Clients](https://mineru.shmakov.tools/getting-started/clients/) for the full comparison.

## The API

Send `{"input": {...}}` to `/runsync` (or `/run`). The most-used fields:

| Field | Required | Default | Notes |
|---|---|---|---|
| `file_url` / `file_b64` / `volume_path` | exactly one | — | Public URL, base64 bytes, or an absolute container path under the worker's input roots. Format auto-detected. |
| `tier` | no | `"standard"` | `flash` / `basic` / `standard` / `advanced` — MinerU's quality tiers, for PDFs and images; other formats always run `flash` |
| `page_range` | no | whole document | PDFs only. MinerU's 1-based grammar: `"1-5,8"`, `"r3-r1"` (`r1` = last page) |
| `transport` | no | `"tarball_b64"` | `tarball_b64` / `inline` / `s3` — how output ships back |
| `formats` | no | `markdown`, `content_list`, `middle`, `images` | What `inline` returns; archives always carry those plus `content_list_v2` and `structured_content`. The renders `html` / `latex` / `docx` / `epub` / `pdf` are made only when listed |

Also under MinerU's own names: `ocr_mode` (`auto` / `txt` / `ocr`), `file_name` (an extension hint for CSV/TSV and HTML fragments) and `server_url` (an external OpenAI-compatible VLM server). Scanned pages in scripts other than Chinese, Japanese and Latin need `standard` or `advanced`: MinerU 4's OCR model covers only those, and it has no per-language switch.

Responses wrap each file in a `results: [...]` list alongside a top-level `debug` block; failures set `ok=false` with a top-level `error`. The full field list, per-transport response shapes, and validation rules live in the **[API reference](https://mineru.shmakov.tools/reference/api/)**.

Under that contract, this repo is the MinerU half: the MinerU call, the input schema and the job envelope. Fetching the input, checking outbound targets, packing the response, structured logging and the model-cache probe come from [`runpod-doc-worker`](https://github.com/sergeyshmakov/runpod-doc-worker) ([docs](https://rdw.shmakov.tools)), an engine-agnostic harness extracted from this worker. What this worker declares to it — its env prefix, input roots and output manifest — is one file, [`worker/harness.py`](worker/harness.py).

## Compared with other parsers

Parsing accuracy is MinerU's domain; their published [OmniDocBench](https://github.com/opendatalab/OmniDocBench) leaderboard puts the 1.2B VLM ahead of much larger general-purpose models:

[![MinerU2.5-Pro-2605 vs other PDF parsers — OmniDocBench leaderboard](https://hotelll.github.io/MinerU2.5-Pro/leaderboard.png)](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B)

<sub>Source: [MinerU2.5-Pro-2605-1.2B model card](https://huggingface.co/opendatalab/MinerU2.5-Pro-2605-1.2B) and the [MinerU 2.5 technical report](https://arxiv.org/abs/2604.04771).</sub>

| | mineru-runpod (this) | Marker | GROBID | Nougat |
|---|---|---|---|---|
| Scale-to-zero | ✅ ready to use | ⚠️ possible, needs extra setup | ❌ (always-on) | ❌ |
| GPU support | GPU only | CPU or GPU | CPU | GPU required |
| Equations | ✅ LaTeX | ✅ LaTeX | ❌ | ✅ LaTeX |
| Multi-lang | ⚠️ OCR model reads Chinese, Japanese and Latin scripts; scans in other scripts need the VLM tiers | per upstream README | EN only | per upstream README |
| Setup time | 5 min | 10 min | 30 min | 20 min |
| License | MinerU Open Source License\* | **GPL-3.0 code + modified RAIL-M weights**\*\* | Apache 2.0 | MIT code + **CC-BY-NC 4.0 weights** |
| Commercial SaaS | ✅ permitted below stated thresholds\* | ⚠️ depends on RAIL-M competitor clause\*\* | ✅ free | ⚠️ subject to CC-BY-NC non-commercial clause |

<sub>\*The MinerU Open Source License is based on Apache 2.0, requires attribution for third-party online services, and requires a separate commercial license when consolidated monthly active users exceed 100 million or total monthly revenue exceeds USD 20 million. Review the [current upstream license](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md) for your use case.</sub>

<sub>\*\*Marker's code is GPL-3.0; its OCR engine (Surya) ships under a modified RAIL-M licence whose §2(c) prohibits use by entities that "provide … any product or service that competes with … Licensor." Datalab's own README says Marker is free for "startups under $2M funding/revenue" — that carveout doesn't appear in the literal licence text, so the two read differently. Verify the current licence against your own usage with counsel before depending on Marker for a competing service. Datalab ships [Chandra](https://github.com/datalab-to/chandra) (the model behind their hosted API) under the same modified RAIL-M licence. See [Surya MODEL_LICENSE](https://github.com/datalab-to/surya/blob/master/MODEL_LICENSE) and [Chandra MODEL_LICENSE](https://github.com/datalab-to/chandra/blob/master/MODEL_LICENSE).</sub>

The license row matters for production use. Marker pairs GPL-3.0 code with modified RAIL-M weights whose competitor clause warrants review. Nougat's model weights are CC-BY-NC 4.0. GROBID is Apache 2.0. MinerU uses its own Apache-based license with additional terms, so evaluate the current upstream text rather than treating any of these projects as interchangeable on licensing.

## Documentation

The docs site covers the rest:

- **[Overview](https://mineru.shmakov.tools/getting-started/overview/)** — what it is, who it's for, architecture
- **[Upgrading to 2.x](https://mineru.shmakov.tools/getting-started/upgrade-to-2/)** — every 1.x field and env var mapped onto MinerU 4.1
- **[Deploy](https://mineru.shmakov.tools/getting-started/deploy/)** — Hub one-click, fork-and-build, or BYO image
- **[Clients](https://mineru.shmakov.tools/getting-started/clients/)** — Python `MineruClient` vs. direct RunPod SDK
- **[Migrate from the MinerU API](https://mineru.shmakov.tools/getting-started/migrate-from-mineru-api/)** — compatibility facade for evaluating a move from the cloud API
- **[Choosing a GPU](https://mineru.shmakov.tools/guides/choosing-gpu/)** — workload-to-pool map, when to bump VRAM
- **[API reference](https://mineru.shmakov.tools/reference/api/)** — JSON payload contract, response shapes, validation rules
- **[Blog](https://mineru.shmakov.tools/blog/)** — launch posts and project notes

## Versioning

| Version part | Moves when |
|---|---|
| **Major** | MinerU itself has a major release (currently pinned `mineru[torch]>=4.1.3,<4.2.0`) |
| **Minor** | New features, and breaking changes to the job contract -- these lead the release notes under **Job Contract Changes** |
| **Patch** | Fixes and internal work |

The major is reserved for the engine because that is the change that moves output
quality and behaviour. A template-contract break ships on a minor, so **read the
release notes before upgrading a minor** -- they lead with anything that needs
action.

A change that breaks `pip install mineru-client` -- a raised Python floor, a dropped
import path -- is also a minor, under **Compatibility Changes**. It is not a major:
nothing range-pins a git-URL install, so the release notes are what reach you, and
spending the major there would put it permanently out of step with MinerU.

The engine version is stated in the docs compatibility table rather than encoded in
the version number.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Commits follow [Conventional Commits](https://www.conventionalcommits.org/); commitlint enforces this in CI and `CHANGELOG.md` is generated automatically by semantic-release on push to `main`.

## Support this project

If this saves you time, the cheapest way to support development is to **[sign up for RunPod through this link](https://runpod.io?ref=31jdfpnq)**. Costs you nothing extra and lets the maintainer keep iterating.

## License

The wrapper code is [MIT](LICENSE). The underlying [MinerU](https://github.com/opendatalab/MinerU) and its model retain the [MinerU Open Source License](https://github.com/opendatalab/MinerU/blob/master/LICENSE.md); the [RunPod SDK](https://github.com/runpod/runpod-python) is MIT.
