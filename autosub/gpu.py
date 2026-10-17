"""Which accelerator VieNeu can use on this machine. torch is imported lazily (it is only in the full image)."""
import functools
import importlib.util

DEVICES = ("auto", "cpu", "cuda")
# VieNeu v3 Turbo on PyTorch needs a GPU with enough memory and a recent architecture
MIN_VRAM_GB = 3.5
MIN_CAPABILITY = (6, 0)

@functools.lru_cache(maxsize=1)
def cuda_info() -> dict:
    """{"available", "name", "vram_gb", "capability", "torch", "cuda", "reason"} (cached: probing CUDA is slow)."""
    info = {"available": False, "name": "", "vram_gb": 0.0, "capability": "", "torch": "", "cuda": "", "reason": ""}
    if importlib.util.find_spec("torch") is None:
        info["reason"] = "Bản cài này không có PyTorch"
        return info
    try:
        import torch
    except Exception as e:  # noqa: BLE001
        info["reason"] = f"Không nạp được PyTorch: {e}"
        return info
    info["torch"] = torch.__version__
    info["cuda"] = torch.version.cuda or ""
    if not torch.version.cuda:
        info["reason"] = "Image đang dùng PyTorch bản CPU (build bản GPU: xem README, mục Chạy VieNeu bằng GPU)"
        return info
    try:
        if not torch.cuda.is_available():
            info["reason"] = "Không thấy GPU NVIDIA trong container (cần driver NVIDIA + NVIDIA Container Toolkit, chạy kèm docker-compose.gpu.yml)"
            return info
        props = torch.cuda.get_device_properties(0)
    except Exception as e:  # noqa: BLE001  (driver too old for this CUDA build, ...)
        info["reason"] = f"Không dùng được GPU: {e}"
        return info
    cap = (props.major, props.minor)
    info.update(name=props.name, vram_gb=round(props.total_memory / (1 << 30), 1), capability=f"{cap[0]}.{cap[1]}")
    if cap < MIN_CAPABILITY:
        info["reason"] = f"GPU {props.name} quá cũ (compute capability {cap[0]}.{cap[1]}, cần ≥ 6.0)"
    elif info["vram_gb"] < MIN_VRAM_GB:
        info["reason"] = f"GPU {props.name} chỉ có {info['vram_gb']} GB VRAM (cần ≥ {MIN_VRAM_GB} GB)"
    else:
        info["available"] = True
    return info

def resolve(requested: str) -> tuple[str, str]:
    """('cuda' | 'cpu', note). "cuda" on a machine without a usable GPU falls back to CPU with a note."""
    requested = (requested or "auto").lower()
    if requested == "cpu":
        return "cpu", ""
    info = cuda_info()
    if info["available"]:
        return "cuda", ""
    if requested == "cuda":
        return "cpu", f"Đã chọn GPU nhưng {info['reason'][:1].lower() + info['reason'][1:]}; VieNeu chạy bằng CPU"
    return "cpu", ""
