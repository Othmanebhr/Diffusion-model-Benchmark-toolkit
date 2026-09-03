from __future__ import annotations

from typing import Any


def generate(request: dict[str, Any]) -> dict[str, Any]:
    """Connect this function to the same internal pipeline used by FastAPI.

    Input keys include:
      source_path, prompt, room_type, style_id, style_number, variant_id,
      prompt_ref, seed, inference, run_id, model_version, catalog_version.

    Supported return forms are documented below. This template deliberately
    raises until the actual model import and invocation are provided.
    """
    # Example only — replace these imports and arguments with the real model code:
    #
    # from app.model_pipeline import generate_virtual_staging
    # image_bytes = generate_virtual_staging(
    #     source_path=request['source_path'],
    #     prompt=request['prompt'],
    #     room_type=request['room_type'],
    #     seed=request['seed'],
    #     **request['inference'],
    # )
    # return {
    #     'image_bytes': image_bytes,
    #     'extension': '.png',
    #     'metadata': {'pipeline': 'virtual-staging-v1'},
    # }
    raise NotImplementedError(
        'Connect adapters/internal_model_template.py to the internal model generation function'
    )


# The adapter may return any one of the following:
#
# 1. Raw image bytes:
#    return png_bytes
#
# 2. A local output path:
#    return '/tmp/generated.png'
#
# 3. A structured result:
#    return {
#        'image_bytes': png_bytes,       # or image_base64 / output_path
#        'extension': '.png',
#        'metadata': {'gpu_seconds': 8.4, 'model_revision': 'abc123'},
#    }

