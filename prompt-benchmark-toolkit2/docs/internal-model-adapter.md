# Internal model adapter

The benchmark calls the same internal Python generation function used by FastAPI. It
does not call FastAPI and does not create an HTTP endpoint.

Load the model once per process. The adapter receives one source image and exactly one
of the catalog prompts:

    def generate(request):
        return model.generate_image(
            source_path=request['source_path'],
            prompt=request['prompt'],
            seed=request['seed'],
            room_type=request['room_type'],
            **request['inference'],
        )

The adapter must:

1. read request['source_path'];
2. pass request['prompt'] to the model without adding, removing or rewriting text;
3. apply the seed and inference parameters when supported;
4. return PNG, JPEG or WebP bytes, a path, or a structured result accepted by the runner;
5. let exceptions propagate so the runner records the failure and continues.

Relevant request fields:

    {
        'case_id': '...',
        'run_id': 'modern-arabic-v1',
        'source_image_id': 'living-diner-001',
        'source_path': '/absolute/path/image.jpg',
        'source_sha256': '...',
        'room_type': 'living_diner_room',
        'mode': 'staging',
        'style_id': 'modern_arabic',
        'style_number': 1,
        'style_name': 'Modern Arabic',
        'variant_id': 'MA-LR-P01',
        'variant_label': 'Warm Modern Arabic',
        'prompt_ref': 'P.1.1',
        'seed': 42,
        'inference': {},
        'prompt': '<exact prompt from catalog>',
        'prompt_sha256': '...',
        'catalog_version': 'modern-arabic-prompts-30-v1',
        'model_version': '...'
    }

The benchmark remains separate from production:

- it runs directly inside the model environment;
- it never writes into the StagingOS database or production storage;
- the catalog contains only the 30 supplied Modern Arabic prompts.
