# MinerU on RunPod Serverless — generic PDF parsing worker.
# MinerU 3.4.x runtime, MinerU2.5-Pro-2605-1.2B VLM as the default model.
#
# Base image: vllm/vllm-openai (recommended by MinerU upstream — bundles CUDA
# + a working vLLM that the VLM backend depends on).
#
# At runtime: handler.py listens for RunPod jobs, downloads/decodes the input
# PDF, calls MinerU's async parse, and returns the result as a base64 tarball.
#
# Model weights are baked into the image at build time (under HF's default
# cache at /root/.cache/huggingface). RunPod's Cached Models
# dashboard feature only supports one model per endpoint, and MinerU needs
# two: the VLM (opendatalab/MinerU2.5-Pro-2605-1.2B) and the pipeline-
# backend model set (opendatalab/PDF-Extract-Kit-1.0). Baking both removes
# the dependency on RunPod's Cached Models setup, the Network Volume, and
# any per-endpoint runtime-download tax. Trade-off: image grows by ~4 GB.

ARG VLLM_VERSION=v0.11.2
FROM vllm/vllm-openai:${VLLM_VERSION}

# HF_HUB_OFFLINE=1 + TRANSFORMERS_OFFLINE=1 force the HuggingFace libs to
# read from cache only. Since model weights are baked into the image, the
# cache is always present. Offline mode prevents accidental downloads if
# anything tries to call out at runtime — fail-fast against misconfigured
# endpoints.
#
# Model selection: MinerU 3.4.x's library default is
# `opendatalab/MinerU2.5-Pro-2605-1.2B` for the VLM backend; pipeline +
# hybrid backends use `opendatalab/PDF-Extract-Kit-1.0` (its OCR set was
# upgraded to PP-OCRv6 in 3.4 — the weights live inside that same repo, so
# a rebuild picks them up with no new bake step). Both repos are baked
# below. Note: MinerU can bump the VLM default on minor-version releases
# (3.1→3.2 bumped 2604→2605); the requirements.txt pin is minor-locked to
# keep the baked models in sync with the library default.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# vllm-openai inherits an entrypoint that launches the OpenAI server. Override
# it so our handler can be the process.
ENTRYPOINT []

# System deps. The base image already has CUDA + Python; we only need the
# things mineru/pdf processing want at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        poppler-utils \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /worker

# Install uv (10x+ faster than pip on resolution-heavy installs like
# mineru[core,vllm], which churns through pydantic / opencv / numpy
# version conflicts with the base image). Negligible image size (~10 MB)
# in exchange for a meaningful build-time win.
# hadolint ignore=DL3013
RUN pip install --no-cache-dir uv

# Install MinerU + RunPod worker SDK. mineru[core,vllm] pulls the VLM-engine
# dependencies that match the vllm version in the base image.
COPY requirements.txt /worker/requirements.txt
RUN uv pip install --system --no-cache -r requirements.txt

# Bake both MinerU model dependencies into the image at /root/.cache/huggingface
# (HF's default cache path). Runs AFTER pip install so huggingface_hub is
# available, and BEFORE the handler.py COPY so iterating on handler code
# doesn't bust these layers.
#
# - MinerU2.5-Pro-2605-1.2B: the VLM backend's model
# - PDF-Extract-Kit-1.0: the pipeline backend's OCR + layout + formula +
#   table models
#
# Split into two RUN layers (one per model) so a partial failure or a
# bump to a single model only re-downloads that model, not both. The
# ~30-minute RunPod build ceiling makes this resilience valuable.
#
# HF_XET_HIGH_PERFORMANCE=1 tells the Xet backend (hf-xet, pinned in
# requirements.txt) to saturate the build node's network bandwidth and
# CPU cores during the snapshot pull. Replaces the now-deprecated
# HF_HUB_ENABLE_HF_TRANSFER flag — Hugging Face has moved all transfers
# to the Xet storage backend, so hf_transfer is no longer used.
#
# HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE are set to "0" inline for these
# RUN steps only — the image-wide ENV directive above keeps them at "1"
# so that runtime stays in offline mode. Without this inline override
# the build would fail with LocalEntryNotFoundError (we'd be trying to
# download with offline mode forced on).
# hadolint ignore=DL3059
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 HF_XET_HIGH_PERFORMANCE=1 \
    python3 -c "from huggingface_hub import snapshot_download; \
    snapshot_download(repo_id='opendatalab/MinerU2.5-Pro-2605-1.2B')"
# hadolint ignore=DL3059
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 HF_XET_HIGH_PERFORMANCE=1 \
    python3 -c "from huggingface_hub import snapshot_download; \
    snapshot_download(repo_id='opendatalab/PDF-Extract-Kit-1.0')"

# Copy the worker code last so iterating on it doesn't bust the pip or
# model-cache layers. handler.py is the entry point; the worker/ package
# holds the modules it imports (schema, io, parse, package, debug,
# logging). Both must land at /worker/ so `from worker import ...`
# resolves from the script's directory.
COPY handler.py /worker/handler.py
COPY worker /worker/worker

# Tiny fixture PDF used by local smoke input and optional Hub tests. It is
# copied into /worker/test-fixture.pdf so validations can round-trip a real
# document without adding meaningful image size.
COPY .runpod/test-fixture.pdf /worker/test-fixture.pdf

# RunPod's serverless runtime invokes Python directly. `python3` is what
# vllm/vllm-openai ships on PATH; `python` is not always aliased.
CMD ["python3", "-u", "handler.py"]
