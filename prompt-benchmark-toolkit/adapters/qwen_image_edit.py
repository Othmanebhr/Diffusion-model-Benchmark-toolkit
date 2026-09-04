"""Adapter: Qwen-Image-Edit-2511 (https://huggingface.co/Qwen/Qwen-Image-Edit-2511).

Runs in its own environment, separate from the HiDream-O1 pod: this pulls in
`diffusers` (from git) + a 20B bf16 transformer + a Qwen2.5-VL-class text
encoder (~57.7 GB on disk together). Do not install this into the same venv
as Image_docker/requirements.txt, which deliberately excludes diffusers.

Usage from the toolkit directory:

    python3 benchmark_cli.py run \
      --manifest runs/qwen-2511-smoke/manifest.json \
      --output-dir runs/qwen-2511-smoke/output \
      --adapter adapters.qwen_image_edit:generate

Environment variables:
    QWEN_MODEL_PATH     Local weights dir or HF repo id
                         (default: "Qwen/Qwen-Image-Edit-2511").
    QWEN_CPU_OFFLOAD    "1" to call enable_model_cpu_offload() (lower peak
                         VRAM, slower). "0" to keep everything resident on
                         the GPU. Default "1" — safe on a 40 GB card, and
                         still cheap insurance on 80 GB while validating.
    QWEN_TRUE_CFG_SCALE  Default true_cfg_scale when the manifest's
                          `inference` dict does not set one (default 4.0).
"""

from __future__ import annotations

import io
import os
import threading
from typing import Any

import torch
from PIL import Image

MODEL_PATH = os.environ.get("QWEN_MODEL_PATH", "Qwen/Qwen-Image-Edit-2511")
CPU_OFFLOAD = os.environ.get("QWEN_CPU_OFFLOAD", "1") != "0"

DEFAULT_NUM_INFERENCE_STEPS = 40
DEFAULT_TRUE_CFG_SCALE = float(os.environ.get("QWEN_TRUE_CFG_SCALE", "4.0"))
DEFAULT_NEGATIVE_PROMPT = " "

_pipeline = None
_load_lock = threading.Lock()


def _get_pipeline():
    """Load the pipeline once per process (mirrors Image_docker/model.py's
    lazy singleton — the benchmark runner is a long-lived sequential loop,
    not one process per case)."""
    global _pipeline
    if _pipeline is None:
        with _load_lock:
            if _pipeline is None:
                from diffusers import QwenImageEditPlusPipeline

                assert torch.cuda.is_available(), "CUDA is required for inference."
                pipe = QwenImageEditPlusPipeline.from_pretrained(
                    MODEL_PATH, torch_dtype=torch.bfloat16
                )
                if CPU_OFFLOAD:
                    pipe.enable_model_cpu_offload()
                else:
                    pipe.to("cuda")
                pipe.set_progress_bar_config(disable=True)
                _pipeline = pipe
    return _pipeline


def generate(request: dict[str, Any]) -> dict[str, Any]:
    pipe = _get_pipeline()
    inference = request.get("inference") or {}

    source_image = Image.open(request["source_path"]).convert("RGB")
    generator = torch.Generator(device="cpu").manual_seed(request["seed"])

    call_kwargs: dict[str, Any] = {
        "image": [source_image],
        "prompt": request["prompt"],
        "generator": generator,
        "true_cfg_scale": DEFAULT_TRUE_CFG_SCALE,
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
        "num_inference_steps": inference.get("steps", DEFAULT_NUM_INFERENCE_STEPS),
    }
    if inference.get("width") and inference.get("height"):
        call_kwargs["width"] = inference["width"]
        call_kwargs["height"] = inference["height"]

    with torch.inference_mode():
        output = pipe(**call_kwargs)
    result_image = output.images[0]

    buffer = io.BytesIO()
    result_image.save(buffer, format="PNG")

    return {
        "image_bytes": buffer.getvalue(),
        "extension": ".png",
        "metadata": {
            "pipeline": "qwen-image-edit-2511",
            "model_path": MODEL_PATH,
            "num_inference_steps": call_kwargs["num_inference_steps"],
            "true_cfg_scale": call_kwargs["true_cfg_scale"],
            "cpu_offload": CPU_OFFLOAD,
        },
    }
