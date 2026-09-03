# Modern Arabic Prompt Benchmark Toolkit

This standalone toolkit evaluates the 30 supplied Modern Arabic prompts against the
internal Python image-generation function running on the RunPod Pod.

The prompt source of truth is:

    catalog/modern_arabic_prompts_30.json

It contains exactly:

- 10 living/dining-room prompts;
- 10 bedroom prompts;
- 10 studio prompts.

The toolkit passes each prompt value to the model exactly as stored. It does not add
guardrails, room modules, furniture anchors, prefixes or suffixes.

## Files

- benchmark_cli.py: build, run and evaluate a benchmark.
- prompt_benchmark/catalog.py: validate and normalize technical identifiers around
  the source JSON without changing prompt text.
- prompt_benchmark/manifest.py: create deterministic test cases.
- prompt_benchmark/runner.py: sequential, resumable execution.
- prompt_benchmark/evaluation.py: blind evaluation template and ranking.
- adapters/internal_model_template.py: template to connect to the internal model.
- config/source_manifest.example.json: example source-image configuration.
- config/finalists.example.json: example reduced prompt selection.

The toolkit is independent from the StagingOS Next.js application and should not be
exposed as a public FastAPI endpoint.

## 1. Prepare source images

Copy the example:

    cp config/source_manifest.example.json config/source_manifest.json

Set an absolute path for at least one test image. Room types are:

- living_diner_room;
- bedroom;
- studio.

Every source image is tested only with prompts written for its room type.

## 2. Build the manifest

From the toolkit directory:

    python3 benchmark_cli.py plan \
      --catalog catalog/modern_arabic_prompts_30.json \
      --sources config/source_manifest.json \
      --output runs/modern-arabic-v1/manifest.json \
      --run-id modern-arabic-v1 \
      --seeds 42 \
      --model-version hdream-o1

With one source image for each of the three room types and one seed, this produces 30
cases. Two seeds produce 60 cases.

Technical identifiers are generated deterministically:

- living/dining room: MA-LR-P01 to MA-LR-P10;
- bedroom: MA-BR-P01 to MA-BR-P10;
- studio: MA-ST-P01 to MA-ST-P10;
- prompt references: P.1.1 to P.1.30.

These identifiers are metadata only. They do not alter prompt text.

## 3. Test a reduced candidate set

Pass a candidate file containing globally unique variant IDs:

    python3 benchmark_cli.py plan \
      --catalog catalog/modern_arabic_prompts_30.json \
      --sources config/source_manifest.json \
      --candidates config/finalists.example.json \
      --output runs/finalists/manifest.json \
      --run-id finalists \
      --seeds 42

## 4. Connect the model

Copy adapters/internal_model_template.py to a model-specific adapter and implement its
generate(request) function. See docs/internal-model-adapter.md.

The adapter must use request['prompt'] exactly. The runner should call the internal
Python function directly rather than the public FastAPI route.

## 5. Dry-run

    python3 benchmark_cli.py run \
      --manifest runs/modern-arabic-v1/manifest.json \
      --output-dir runs/modern-arabic-v1/output \
      --dry-run

## 6. Run on the Pod

    python3 benchmark_cli.py run \
      --manifest runs/modern-arabic-v1/manifest.json \
      --output-dir runs/modern-arabic-v1/output \
      --adapter adapters.staging_model:generate

The run is sequential and resumable. Re-running the same command skips successful
cases already present in results.jsonl.

## 7. Evaluate and rank

    python3 benchmark_cli.py evaluation-template \
      --results runs/modern-arabic-v1/output/results.jsonl \
      --output runs/modern-arabic-v1/evaluation.csv

    python3 benchmark_cli.py score \
      --evaluation runs/modern-arabic-v1/evaluation.csv \
      --ranking runs/modern-arabic-v1/ranking.csv \
      --finalists runs/modern-arabic-v1/finalists.json \
      --top-k 3

Top-k keeps up to that many passing prompts per room type. Architecture preservation
and camera perspective remain hard quality gates.
