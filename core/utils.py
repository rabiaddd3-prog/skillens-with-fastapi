"""Reproducibility helpers: seeding, device choice, and a run record for reports."""
from __future__ import annotations

import json
import platform
import random
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import numpy as np
import torch


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device(preference: str = "auto") -> torch.device:
    """auto -> cuda, then Apple mps, then cpu. Same code runs on Windows and Mac."""
    if preference != "auto":
        return torch.device(preference)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def device_name(device: torch.device) -> str:
    if device.type == "cuda":
        return torch.cuda.get_device_name(device)
    return device.type


def run_info(device: torch.device, args: dict) -> dict:
    """Everything needed to describe a run in the report: settings, versions, hardware."""
    packages = {}
    for name in ("torch", "transformers", "datasets", "numpy", "seqeval"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            pass
    return {
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "args": args,
        "device": device_name(device),
        "cuda": torch.version.cuda,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": packages,
    }


def write_json(path: str | Path, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
