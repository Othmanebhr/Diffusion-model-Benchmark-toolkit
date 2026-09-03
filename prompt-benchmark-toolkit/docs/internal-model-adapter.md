# Internal model adapter

The benchmark must call the same Python generation function used by FastAPI, but it must not call FastAPI itself and must not create a new HTTP endpoint.

## Lifecycle

Load the model once per benchmark process. Do not construct or reload model weights inside `generate()`.

```python
from app.model_runtime import get_model_runtime

RUNTIME = get_model_runtime()


def generate(request):
    return RUNTIME.generate(
        source_path=request['source_path'],
        prompt=request['prompt'],
        seed=request['seed'],
        room_type=request['room_type'],
        **request['inference'],
    )
```

If the FastAPI application already owns a singleton runtime, import the shared runtime factory or pipeline module rather than importing the FastAPI route handler.

## Required behavior

The adapter must:

1. read the source image from `request['source_path']`;
2. use `request['prompt']` exactly as provided;
3. apply `request['seed']` deterministically when the model supports seeds;
4. apply the frozen inference parameters in `request['inference']`;
5. return PNG, JPEG, or WebP bytes/path;
6. avoid writing to the production StagingOS database or production object keys;
7. allow exceptions to propagate so the runner records the failed case and continues.

## Complete request shape

```python
{
    'case_id': '...',
    'pilot_case_id': 'ST-0001',
    'run_id': 'smoke-v3',
    'source_image_id': 'living-diner-001',
    'source_path': '/absolute/path/image.jpg',
    'source_sha256': '...',
    'room_type': 'living_diner_room',
    'mode': 'staging',
    'style_id': 'modern_arabic',
    'style_number': 1,
    'style_name': 'Modern Arabic',
    'variant_id': 'MA-P01',
    'prompt_ref': 'P.1.1',
    'anchor_id': 'MA-P1-LD',
    'seed': 42,
    'inference': {...},
    'prompt': 'complete assembled instruction',
    'prompt_sha256': '...',
    'catalog_version': 'v3',
    'model_version': '...'
}
```

For No Furniture, `mode` is `no_furniture`, `style_id` is `empty`, `style_number` is `7`, and `anchor_id` is empty.

## Important separation

The benchmark runner controls exact prompt variants. The production FastAPI behavior remains:

- `/generate`: produce the seven production styles according to the approved prompt pool;
- `/regenerate`: use the active `prompt_ref` values to choose new approved variants;
- StagingOS never receives or manages the prompt texts.

