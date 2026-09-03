#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from prompt_benchmark.evaluation import create_evaluation_template, score_evaluations
from prompt_benchmark.manifest import build_manifest
from prompt_benchmark.runner import run_manifest


def csv_ints(value: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in value.split(',') if part.strip()]
    except ValueError as error:
        raise argparse.ArgumentTypeError('Seeds must be comma-separated integers') from error
    if not values:
        raise argparse.ArgumentTypeError('At least one seed is required')
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Virtual staging prompt benchmark toolkit')
    commands = parser.add_subparsers(dest='command', required=True)

    plan_command = commands.add_parser('plan', help='Build a deterministic run manifest')
    plan_command.add_argument('--catalog', type=Path, required=True)
    plan_command.add_argument('--sources', type=Path, required=True)
    plan_command.add_argument('--output', type=Path, required=True)
    plan_command.add_argument('--run-id', required=True)
    plan_command.add_argument('--seeds', type=csv_ints, default=[42])
    plan_command.add_argument('--candidates', type=Path)
    plan_command.add_argument('--model-version', default='unconfigured')
    plan_command.add_argument('--temperature', type=float)
    plan_command.add_argument('--top-p', type=float)
    plan_command.add_argument('--steps', type=int)
    plan_command.add_argument('--edit-strength', type=float)
    plan_command.add_argument('--width', type=int)
    plan_command.add_argument('--height', type=int)

    run_command = commands.add_parser('run', help='Run or dry-run a benchmark manifest')
    run_command.add_argument('--manifest', type=Path, required=True)
    run_command.add_argument('--output-dir', type=Path, required=True)
    run_command.add_argument('--adapter', help='Python callable in module:function form')
    run_command.add_argument('--dry-run', action='store_true')
    run_command.add_argument('--limit', type=int)

    template_command = commands.add_parser(
        'evaluation-template', help='Create a CSV for blind human evaluation'
    )
    template_command.add_argument('--results', type=Path, required=True)
    template_command.add_argument('--output', type=Path, required=True)

    score_command = commands.add_parser('score', help='Rank evaluated prompt variants')
    score_command.add_argument('--evaluation', type=Path, required=True)
    score_command.add_argument('--ranking', type=Path, required=True)
    score_command.add_argument('--finalists', type=Path, required=True)
    score_command.add_argument('--top-k', type=int, default=5)

    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == 'plan':
        inference = {
            key: value
            for key, value in {
                'temperature': args.temperature,
                'top_p': args.top_p,
                'steps': args.steps,
                'edit_strength': args.edit_strength,
                'width': args.width,
                'height': args.height,
            }.items()
            if value is not None
        }
        manifest = build_manifest(
            catalog_path=args.catalog,
            sources_path=args.sources,
            output_path=args.output,
            run_id=args.run_id,
            seeds=args.seeds,
            candidates_path=args.candidates,
            model_version=args.model_version,
            inference=inference,
        )
        print(f"Created {len(manifest['cases'])} cases in {args.output}")
        return

    if args.command == 'run':
        summary = run_manifest(
            manifest_path=args.manifest,
            output_dir=args.output_dir,
            adapter_spec=args.adapter,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        print(
            f"Run complete: {summary['succeeded']} succeeded, {summary['failed']} failed, "
            f"{summary['skipped']} skipped."
        )
        return

    if args.command == 'evaluation-template':
        count = create_evaluation_template(args.results, args.output)
        print(f'Created {count} evaluation rows in {args.output}')
        return

    if args.command == 'score':
        summary = score_evaluations(
            evaluation_path=args.evaluation,
            ranking_path=args.ranking,
            finalists_path=args.finalists,
            top_k=args.top_k,
        )
        print(f"Ranked {summary['variant_count']} variants; finalists written to {args.finalists}")


if __name__ == '__main__':
    main()
