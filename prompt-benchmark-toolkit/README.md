# Modern Arabic Prompt Benchmark Toolkit

This standalone toolkit evaluates the 30 supplied Modern Arabic prompts against
image-generation models running on a RunPod pod — either the internal HiDream-O1
pipeline or a candidate replacement (currently Qwen-Image-Edit-2511).

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
- adapters/internal_model_template.py: template to wire up the internal HiDream-O1
  pod function (not yet implemented — copy it to a real adapter when you need a
  HiDream baseline run).
- adapters/qwen_image_edit.py: ready-to-use adapter for Qwen-Image-Edit-2511
  (diffusers `QwenImageEditPlusPipeline`). See its docstring for the required env
  vars (`QWEN_MODEL_PATH`, `QWEN_CPU_OFFLOAD`, `QWEN_TRUE_CFG_SCALE`).
- requirements-qwen.txt: dependencies for the Qwen adapter. Install in a venv
  separate from the HiDream pod's — that one deliberately excludes `diffusers`.
- config/source_manifest.json: source-image configuration (edit the paths for
  your pod before running).
- config/finalists.example.json: example reduced prompt selection (one variant
  per room type — use it for a cheap smoke test before a full 30-prompt run).

The toolkit is independent from the StagingOS Next.js application and should not be
exposed as a public FastAPI endpoint.

## 1. Prepare source images

Edit `config/source_manifest.json` and set an absolute path (on the pod) for at
least one test image per room type:

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

For Qwen-Image-Edit-2511, `adapters/qwen_image_edit.py` is ready — just install
`requirements-qwen.txt` in its own venv and set `QWEN_MODEL_PATH` to the local
weights directory (see its docstring).

For a HiDream-O1 baseline run, copy adapters/internal_model_template.py to a new
adapter and implement its generate(request) function. See docs/internal-model-adapter.md.

Either way, the adapter must use request['prompt'] exactly, and must call the model
function directly in-process rather than the public FastAPI route.

## 5. Dry-run

    python3 benchmark_cli.py run \
      --manifest runs/modern-arabic-v1/manifest.json \
      --output-dir runs/modern-arabic-v1/output \
      --dry-run

## 6. Run on the Pod

    python3 benchmark_cli.py run \
      --manifest runs/modern-arabic-v1/manifest.json \
      --output-dir runs/modern-arabic-v1/output \
      --adapter adapters.qwen_image_edit:generate

Swap the `--adapter` value for your HiDream adapter's `module:function` path to run
the same manifest against the baseline instead.

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
