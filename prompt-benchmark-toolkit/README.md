# Virtual Staging Prompt Benchmark Toolkit

Local, model-side tooling for compiling the StagingOS prompt workbook, building reproducible benchmark plans, running them against the **internal Python generation function**, and ranking the results.

This directory is intentionally independent from the StagingOS Next.js application. It does not add a FastAPI endpoint and it does not write benchmark jobs into the StagingOS database.

## What is included

- `benchmark_cli.py`: command-line entry point.
- `prompt_benchmark/xlsx_catalog.py`: dependency-free XLSX reader and compiler.
- `prompt_benchmark/catalog.py`: runtime prompt assembler.
- `prompt_benchmark/manifest.py`: deterministic benchmark-plan builder.
- `prompt_benchmark/runner.py`: resumable sequential runner.
- `prompt_benchmark/evaluation.py`: evaluation CSV and ranking generator.
- `adapters/internal_model_template.py`: the only file that must be connected to the actual model pipeline.
- `config/source_manifest.example.json`: expected source-image manifest.
- `config/finalists.example.json`: optional reduced candidate set for later rounds.
- `schemas/`: JSON schemas for the compiled catalog and run manifest.

Only the Python standard library is required by the toolkit. The real model adapter can, of course, use PyTorch, Diffusers, Pillow, or any dependency already present in the RunPod image.

## Recommended placement

Copy this directory into the Python/model repository running on RunPod, for example:

```text
virtual-staging-model/
  app/
  prompt-benchmark-toolkit/
```

Do not expose the benchmark runner as a public FastAPI route. It should run from the Pod terminal or as an internal maintenance command.

## 1. Compile the workbook

```bash
cd prompt-benchmark-toolkit

python3 benchmark_cli.py compile \
  --workbook /path/to/virtual_staging_modular_prompt_benchmark_v3.xlsx \
  --output catalog/prompt_catalog_v3.json \
  --report catalog/catalog_validation_report.json
```

The compiler validates:

- 6 staging styles and their numeric StagingOS/RunPod mapping;
- 30 variants per staging style;
- 3 room types;
- furniture-anchor coverage;
- No Furniture variants;
- pilot matrices;
- exact reconstruction of the assembled standard instructions;
- evaluation weights from the workbook.

The generated catalog preserves both identifiers:

- semantic ID: `MA-P01`;
- StagingOS technical reference: `P.1.1`.

## 2. Prepare benchmark source images

Copy `config/source_manifest.example.json` and replace its paths with real files on the Pod.

For the first smoke test, use one representative image for each room type:

- `living_diner_room`;
- `bedroom`;
- `studio`.

All candidate prompts for a room type are evaluated against the exact same image and inference parameters.

## 3. Build the first benchmark plan

```bash
python3 benchmark_cli.py plan \
  --catalog catalog/prompt_catalog_v3.json \
  --sources config/source_manifest.json \
  --output runs/smoke-v3/manifest.json \
  --run-id smoke-v3 \
  --seeds 42
```

With one source image per room type, the complete pilot contains:

- 360 staging cases;
- 60 No Furniture cases;
- 420 generated images in total.

Use `--no-include-no-furniture` to benchmark only the six furnished styles.

For a reduced later round, pass a finalist file:

```bash
python3 benchmark_cli.py plan \
  --catalog catalog/prompt_catalog_v3.json \
  --sources config/source_manifest.json \
  --candidates config/finalists.json \
  --output runs/finalists-v3/manifest.json \
  --run-id finalists-v3 \
  --seeds 42,137
```

The manifest freezes the complete assembled prompt, its SHA-256, source-image SHA-256, model parameters, catalog version, and test-case identity.

## 4. Connect the internal model function

Copy `adapters/internal_model_template.py` to a model-specific file, such as:

```text
adapters/staging_model.py
```

Implement its single function:

```python
def generate(request: dict) -> dict:
    ...
```

The adapter receives the exact source path, assembled prompt, room type, style, variant, seed, and inference parameters. It must call the **same internal generation function used by FastAPI**, then return image bytes or an output path.

Do not call StagingOS and do not call the public `/generate` endpoint from the benchmark. Direct internal invocation makes prompt selection, seed control, metadata, and failures reproducible.

## 5. Dry-run before using the GPU

```bash
python3 benchmark_cli.py run \
  --manifest runs/smoke-v3/manifest.json \
  --output-dir runs/smoke-v3/output \
  --dry-run
```

The dry-run writes the resolved cases and prompts without invoking the model.

## 6. Run the benchmark

```bash
python3 benchmark_cli.py run \
  --manifest runs/smoke-v3/manifest.json \
  --output-dir runs/smoke-v3/output \
  --adapter adapters.staging_model:generate
```

The runner is sequential by default, which is safer for one persistent GPU Pod. It is resumable: rerunning the same command skips successful cases already recorded in `results.jsonl`.

## 7. Create the human-evaluation file

```bash
python3 benchmark_cli.py evaluation-template \
  --results runs/smoke-v3/output/results.jsonl \
  --output runs/smoke-v3/evaluation.csv
```

Fill the human scores from 1 to 5. Reviewers should not see the variant names while judging images; randomize or mask those labels in the review interface.

Then produce rankings:

```bash
python3 benchmark_cli.py score \
  --evaluation runs/smoke-v3/evaluation.csv \
  --ranking runs/smoke-v3/ranking.csv \
  --finalists runs/smoke-v3/finalists.json \
  --top-k 5
```

Architecture preservation and camera/perspective are hard gates: a score below 4 rejects the result even if its weighted average is high.

## Production prompt policy after the benchmark

Keep a small approved pool per style rather than one global prompt:

- initial generation chooses a prompt from the approved pool;
- regeneration chooses an approved prompt not already used for that photo/style;
- after exhausting the pool, selection may wrap;
- No Furniture should normally use one highly reliable approved prompt and remains non-regenerable in StagingOS.

The production API contract can remain unchanged: StagingOS only needs the returned `P.y.z` reference. The Python prompt catalog owns the actual prompt text and the mapping to semantic IDs such as `MA-P01`.

