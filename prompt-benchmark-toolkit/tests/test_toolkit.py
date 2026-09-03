from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from prompt_benchmark.catalog import assemble_no_furniture_prompt, assemble_staging_prompt
from prompt_benchmark.manifest import build_manifest
from prompt_benchmark.runner import run_manifest
from prompt_benchmark.xlsx_catalog import compile_workbook


WORKBOOK = Path(
    '/Users/mariefrancoi/Desktop/prompt_stagingOS/virtual_staging_modular_prompt_benchmark_v3.xlsx'
)


class ToolkitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not WORKBOOK.exists():
            raise unittest.SkipTest(f'Workbook not available: {WORKBOOK}')
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.catalog_path = root / 'catalog.json'
        cls.report_path = root / 'report.json'
        cls.report = compile_workbook(WORKBOOK, cls.catalog_path, cls.report_path, 'v3-test')
        cls.catalog = json.loads(cls.catalog_path.read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_catalog_counts_and_prompt_reconstruction(self) -> None:
        self.assertEqual(self.report['style_variant_count'], 180)
        self.assertEqual(self.report['furniture_anchor_count'], 108)
        self.assertEqual(self.report['style_pilot_case_count'], 360)
        self.assertEqual(self.report['no_furniture_pilot_case_count'], 60)
        self.assertEqual(self.report['assembled_prompt_mismatches'], [])

    def test_prompt_references_match_stagingos_contract(self) -> None:
        prompt = assemble_staging_prompt(self.catalog, 'MA-P01', 'bedroom')
        self.assertEqual(prompt['prompt_ref'], 'P.1.1')
        self.assertEqual(prompt['style_id'], 'modern_arabic')
        empty = assemble_no_furniture_prompt(self.catalog, 'NF-P30', 'studio')
        self.assertEqual(empty['prompt_ref'], 'P.7.30')
        self.assertEqual(empty['style_id'], 'empty')

    def test_smoke_manifest_contains_420_cases(self) -> None:
        root = Path(self.temp.name)
        sources = []
        for room_type in ('living_diner_room', 'bedroom', 'studio'):
            image = root / f'{room_type}.jpg'
            image.write_bytes(b'benchmark-source')
            sources.append(
                {
                    'source_image_id': f'{room_type}-001',
                    'room_type': room_type,
                    'path': str(image),
                }
            )
        sources_path = root / 'sources.json'
        sources_path.write_text(json.dumps({'sources': sources}), encoding='utf-8')
        manifest = build_manifest(
            catalog_path=self.catalog_path,
            sources_path=sources_path,
            output_path=root / 'manifest.json',
            run_id='smoke-test',
            seeds=[42],
            candidates_path=None,
            include_no_furniture=True,
            model_version='test',
            inference={},
        )
        self.assertEqual(manifest['case_count'], 420)
        self.assertEqual(len({case['case_id'] for case in manifest['cases']}), 420)

    def test_explicit_candidates_can_include_non_pilot_variants(self) -> None:
        root = Path(self.temp.name)
        image = root / 'candidate-bedroom.jpg'
        image.write_bytes(b'candidate-source')
        sources_path = root / 'candidate-sources.json'
        sources_path.write_text(
            json.dumps(
                {
                    'sources': [
                        {
                            'source_image_id': 'candidate-bedroom',
                            'room_type': 'bedroom',
                            'path': str(image),
                        }
                    ]
                }
            ),
            encoding='utf-8',
        )
        candidates_path = root / 'candidates.json'
        candidates_path.write_text(
            json.dumps(
                {
                    'style_variant_ids': ['MA-P30'],
                    'no_furniture_variant_ids': ['NF-P30'],
                }
            ),
            encoding='utf-8',
        )
        manifest = build_manifest(
            catalog_path=self.catalog_path,
            sources_path=sources_path,
            output_path=root / 'candidate-manifest.json',
            run_id='candidate-test',
            seeds=[42],
            candidates_path=candidates_path,
            include_no_furniture=True,
            model_version='test',
            inference={},
        )
        self.assertEqual(manifest['case_count'], 2)
        self.assertEqual(
            {case['variant_id'] for case in manifest['cases']}, {'MA-P30', 'NF-P30'}
        )

    def test_runner_invokes_internal_adapter_and_is_resumable(self) -> None:
        root = Path(self.temp.name)
        manifest_path = root / 'runner-manifest.json'
        manifest_path.write_text(
            json.dumps(
                {
                    'schema_version': 1,
                    'run_id': 'runner-test',
                    'catalog_version': 'v3-test',
                    'model_version': 'fake',
                    'cases': [
                        {
                            'case_id': 'case-runner-1',
                            'pilot_case_id': 'ST-0001',
                            'source_image_id': 'source-1',
                            'source_path': '/unused/source.jpg',
                            'source_sha256': '0' * 64,
                            'room_type': 'living_diner_room',
                            'mode': 'staging',
                            'style_id': 'modern_arabic',
                            'style_number': 1,
                            'style_name': 'Modern Arabic',
                            'variant_id': 'MA-P01',
                            'prompt_ref': 'P.1.1',
                            'anchor_id': 'MA-P1-LD',
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
        output_dir = root / 'runner-output'
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


if __name__ == '__main__':
    unittest.main()
