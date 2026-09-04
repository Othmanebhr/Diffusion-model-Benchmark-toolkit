from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from prompt_benchmark.catalog import load_catalog
from prompt_benchmark.evaluation import (
    IDENTITY_COLUMNS,
    OTHER_COLUMNS,
    SCORE_COLUMNS,
    score_evaluations,
)
from prompt_benchmark.manifest import build_manifest
from prompt_benchmark.runner import run_manifest


TOOLKIT_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = TOOLKIT_ROOT / 'catalog' / 'modern_arabic_prompts_30.json'
ROOM_SECTIONS = {
    'living_room_prompts': 'living_diner_room',
    'bedroom_prompts': 'bedroom',
    'studio_prompts': 'studio',
}


class ToolkitTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_catalog_contains_only_the_30_exact_source_prompts(self) -> None:
        source = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        catalog = load_catalog(CATALOG_PATH)

        expected = {
            (room_type, row['id']): row['prompt']
            for section, room_type in ROOM_SECTIONS.items()
            for row in source[section]
        }
        actual = {
            (prompt['room_type'], int(prompt['variant_id'][-2:])): prompt['prompt']
            for prompt in catalog['prompts']
        }

        self.assertEqual(len(catalog['prompts']), 30)
        self.assertEqual(actual, expected)
        self.assertEqual(
            len({prompt['prompt_ref'] for prompt in catalog['prompts']}),
            30,
        )
        self.assertEqual(
            len({prompt['variant_id'] for prompt in catalog['prompts']}),
            30,
        )

    def test_manifest_contains_30_cases_for_one_source_per_room(self) -> None:
        sources_path = self._write_sources()
        manifest = build_manifest(
            catalog_path=CATALOG_PATH,
            sources_path=sources_path,
            output_path=self.root / 'manifest.json',
            run_id='modern-arabic-smoke',
            seeds=[42],
            candidates_path=None,
            model_version='test',
            inference={},
        )

        self.assertEqual(manifest['case_count'], 30)
        self.assertEqual(len({case['case_id'] for case in manifest['cases']}), 30)
        self.assertEqual(
            {case['room_type'] for case in manifest['cases']},
            {'living_diner_room', 'bedroom', 'studio'},
        )

    def test_candidate_manifest_filters_by_unique_variant_id(self) -> None:
        sources_path = self._write_sources()
        candidates_path = self.root / 'candidates.json'
        candidates_path.write_text(
            json.dumps({'variant_ids': ['MA-LR-P02', 'MA-BR-P04', 'MA-ST-P06']}),
            encoding='utf-8',
        )
        manifest = build_manifest(
            catalog_path=CATALOG_PATH,
            sources_path=sources_path,
            output_path=self.root / 'candidate-manifest.json',
            run_id='candidate-test',
            seeds=[42],
            candidates_path=candidates_path,
            model_version='test',
            inference={},
        )

        self.assertEqual(manifest['case_count'], 3)
        self.assertEqual(
            {case['variant_id'] for case in manifest['cases']},
            {'MA-LR-P02', 'MA-BR-P04', 'MA-ST-P06'},
        )

    def test_manifest_keeps_prompt_text_byte_for_byte(self) -> None:
        source = json.loads(CATALOG_PATH.read_text(encoding='utf-8'))
        sources_path = self._write_sources()
        manifest = build_manifest(
            catalog_path=CATALOG_PATH,
            sources_path=sources_path,
            output_path=self.root / 'manifest.json',
            run_id='prompt-integrity',
            seeds=[42],
            candidates_path=None,
            model_version='test',
            inference={},
        )

        living_prompt = next(
            case for case in manifest['cases'] if case['variant_id'] == 'MA-LR-P01'
        )
        self.assertEqual(
            living_prompt['prompt'],
            source['living_room_prompts'][0]['prompt'],
        )

    def test_runner_invokes_internal_adapter_and_is_resumable(self) -> None:
        manifest_path = self.root / 'runner-manifest.json'
        manifest_path.write_text(
            json.dumps(
                {
                    'schema_version': 1,
                    'run_id': 'runner-test',
                    'catalog_version': 'modern-arabic-prompts-30-v1',
                    'model_version': 'fake',
                    'cases': [
                        {
                            'case_id': 'case-runner-1',
                            'source_image_id': 'source-1',
                            'source_path': '/unused/source.jpg',
                            'source_sha256': '0' * 64,
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
                            'prompt': 'test prompt',
                            'prompt_sha256': '1' * 64,
                        }
                    ],
                }
            ),
            encoding='utf-8',
        )
        output_dir = self.root / 'runner-output'
        first = run_manifest(
            manifest_path=manifest_path,
            output_dir=output_dir,
            adapter_spec='tests.fake_adapter:generate',
            dry_run=False,
            limit=None,
        )
        second = run_manifest(
            manifest_path=manifest_path,
            output_dir=output_dir,
            adapter_spec='tests.fake_adapter:generate',
            dry_run=False,
            limit=None,
        )
        self.assertEqual(first, {'succeeded': 1, 'failed': 0, 'skipped': 0})
        self.assertEqual(second, {'succeeded': 0, 'failed': 0, 'skipped': 1})
        self.assertTrue((output_dir / 'images' / 'case-runner-1.png').is_file())

    def test_scoring_keeps_finalists_per_room(self) -> None:
        evaluation_path = self.root / 'evaluation.csv'
        fieldnames = IDENTITY_COLUMNS + SCORE_COLUMNS + OTHER_COLUMNS
        with evaluation_path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for room_type, variant_id in (
                ('living_diner_room', 'MA-LR-P01'),
                ('bedroom', 'MA-BR-P01'),
                ('studio', 'MA-ST-P01'),
            ):
                writer.writerow(
                    {
                        'style_id': 'modern_arabic',
                        'room_type': room_type,
                        'variant_id': variant_id,
                        'architecture_preservation': 5,
                        'camera_perspective': 5,
                        'photorealism': 4,
                    }
                )

        finalists_path = self.root / 'finalists.json'
        summary = score_evaluations(
            evaluation_path=evaluation_path,
            ranking_path=self.root / 'ranking.csv',
            finalists_path=finalists_path,
            top_k=1,
        )
        finalists = json.loads(finalists_path.read_text(encoding='utf-8'))

        self.assertEqual(summary, {'variant_count': 3})
        self.assertEqual(
            set(finalists['variant_ids']),
            {'MA-LR-P01', 'MA-BR-P01', 'MA-ST-P01'},
        )

    def _write_sources(self) -> Path:
        sources = []
        for room_type in ('living_diner_room', 'bedroom', 'studio'):
            image = self.root / f'{room_type}.jpg'
            image.write_bytes(b'benchmark-source')
            sources.append(
                {
                    'source_image_id': f'{room_type}-001',
                    'room_type': room_type,
                    'path': str(image),
                }
            )
        sources_path = self.root / 'sources.json'
        sources_path.write_text(json.dumps({'sources': sources}), encoding='utf-8')
        return sources_path


if __name__ == '__main__':
    unittest.main()
