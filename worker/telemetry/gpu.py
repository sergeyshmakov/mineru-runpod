"""GPU gauges, via NVML when it is present.

Every function here answers "nothing to report" rather than raising. A metrics
backend that cannot see the GPU is a degraded observability story; a worker that
crashes because NVML is missing is a broken worker.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from worker.telemetry import state


def _get_nvml() -> Any:
    if state._nvml_init_attempted:
        return state._nvml
    state._nvml_init_attempted = True
    try:
        import pynvml  # noqa: PLC0415
        pynvml.nvmlInit()
        state._nvml = pynvml
        _cache_gpu_handles()
    except Exception:  # noqa: BLE001
        state._nvml = None
    return state._nvml


def _cache_gpu_handles() -> None:
    """Populate ``_nvml_handles`` once per process. Failures leave it empty."""
    if state._nvml is None:
        return
    try:
        count = state._nvml.nvmlDeviceGetCount()
    except Exception:  # noqa: BLE001
        return
    for i in range(count):
        try:
            state._nvml_handles.append((i, state._nvml.nvmlDeviceGetHandleByIndex(i)))
        except Exception:  # noqa: BLE001
            return


def _gpu_handles() -> Iterable[tuple[int, Any]]:
    if _get_nvml() is None:
        return ()
    return state._nvml_handles


def _observe_gpu_mem_used(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    pynvml = _get_nvml()
    if pynvml is None:
        return
    for idx, handle in _gpu_handles():
        try:
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            yield Observation(int(info.used), {"device": str(idx)})
        except Exception:  # noqa: BLE001
            continue


def _observe_gpu_mem_total(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    pynvml = _get_nvml()
    if pynvml is None:
        return
    for idx, handle in _gpu_handles():
        try:
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            yield Observation(int(info.total), {"device": str(idx)})
        except Exception:  # noqa: BLE001
            continue


def _observe_gpu_util(options: Any) -> Iterator[Any]:  # noqa: ARG001
    from opentelemetry.metrics import Observation  # noqa: PLC0415
    pynvml = _get_nvml()
    if pynvml is None:
        return
    for idx, handle in _gpu_handles():
        try:
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            yield Observation(int(util.gpu), {"device": str(idx)})
        except Exception:  # noqa: BLE001
            continue
