# MinerU on RunPod Serverless — document parsing worker.
# MinerU 4.1.x runtime: Torch small models + the MinerU2.5-Pro-2605-1.2B VLM on vLLM.
#
# Base image: vllm/vllm-openai, as MinerU's own Docker image uses — it bundles
# CUDA and the vLLM engine the standard and advanced tiers run on.
#
# At runtime: handler.py listens for RunPod jobs, fetches the input, calls
# MinerU's async parse, and returns the result (tarball, inline or s3).
#
# Model weights are baked into the image at build time, under MinerU's own
# model root (/opt/mineru/models): the small-model bundle
# (opendatalab/MinerU-4_models_torch) and the VLM
# (opendatalab/MinerU2.5-Pro-2605-1.2B). Baking removes any dependency on
# RunPod's Cached Models, a Network Volume, or a per-endpoint download tax.

# The vLLM release MinerU validates its 4.x image on, in the CUDA 12.9 build so
# hosts on 12.9 and 13.0 drivers both qualify (hub.json allowedCudaVersions).
# MinerU 4.1 accepts vllm >=0.19.1,<0.31.0.
ARG VLLM_VERSION=v0.21.0-cu129
FROM vllm/vllm-openai:${VLLM_VERSION}

# MinerU 4 reads its settings from MINERU_* variables (they override
# $MINERU_HOME/config.yaml, which the image never writes):
#   - MINERU_MODEL_SMALL_BACKEND / MINERU_MODEL_VLM_ENGINE fix the backends the
#     weights below are downloaded for. Left on auto, a build machine without a
#     GPU would pick ONNX + llama.cpp and download a different set.
#   - MINERU_TELEMETRY_DISABLED: MinerU's anonymous telemetry lives in its
#     local document library, which this worker never starts; set anyway so the
#     image's no-phone-home stance does not depend on that.
# HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE keep vLLM and transformers from
# reaching for the network at runtime. MinerU itself does not read them; it is
# kept offline by MINERU_MODEL_SOURCE=local, set after the download below.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    MINERU_HOME=/opt/mineru \
    MINERU_MODEL_SMALL_BACKEND=torch \
    MINERU_MODEL_VLM_ENGINE=vllm \
    MINERU_TELEMETRY_DISABLED=1

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
# mineru[torch], which churns through pydantic / numpy / transformers
# versions against the base image). Negligible image size (~10 MB) in
# exchange for a meaningful build-time win. --break-system-packages is a
# no-op unless the base image marks its Python as externally managed, which
# MinerU's own Dockerfile allows for on this base.
# hadolint ignore=DL3013
RUN pip install --no-cache-dir --break-system-packages uv

# Install MinerU + RunPod worker SDK. mineru[torch] reuses the base image's
# vLLM rather than installing its own.
COPY requirements.txt /worker/requirements.txt
RUN uv pip install --system --break-system-packages --no-cache -r requirements.txt

# Bake the models the standard and advanced tiers load (basic needs only the
# first; flash needs neither for text layers and native formats, and only the
# small models for scans). Runs AFTER the install so `mineru-kit` exists, and
# BEFORE the handler COPY so iterating on handler code doesn't bust this layer.
#
# `models download` writes MinerU's completion markers, which is what makes the
# files count as ready; `models verify` fails the build if anything is missing.
# The backends are named explicitly for the same reason as the ENV above, and
# `--source` explicitly so the build never writes a config.yaml.
#
# HF_XET_HIGH_PERFORMANCE=1 lets the Xet backend (hf-xet, in requirements.txt)
# saturate the build node's network during the pull. HF_HUB_OFFLINE is lifted
# for this step only; the image-wide ENV above keeps runtime offline.
# hadolint ignore=DL3059
RUN HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 HF_XET_HIGH_PERFORMANCE=1 \
    mineru-kit models download --tier standard --small-backend torch \
        --vlm-engine vllm --source huggingface \
    && mineru-kit models verify --tier standard --small-backend torch --vlm-engine vllm

# From here on MinerU uses the baked models and never downloads: a missing
# file fails fast instead of reaching for a network the endpoint may not have.
ENV MINERU_MODEL_SOURCE=local

# Copy the worker code last so iterating on it doesn't bust the pip or
# model layers. handler.py is the entry point; the worker/ package holds the
# MinerU-specific modules it imports (harness, schema, inputs, models, parse,
# telemetry, warmup) — the engine-agnostic half came from the
# runpod-doc-worker pin above. Both must land at /worker/ so
# `from worker import ...` resolves from the script's directory.
COPY handler.py /worker/handler.py
COPY worker /worker/worker

# Tiny fixture PDF used by local smoke input and optional Hub tests. It is
# copied into /worker/test-fixture.pdf so validations can round-trip a real
# document without adding meaningful image size.
COPY .runpod/test-fixture.pdf /worker/test-fixture.pdf

# RunPod's serverless runtime invokes Python directly. `python3` is what
# vllm/vllm-openai ships on PATH; `python` is not always aliased.
CMD ["python3", "-u", "handler.py"]
