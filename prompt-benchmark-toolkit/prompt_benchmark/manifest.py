from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .catalog import assemble_no_furniture_prompt, assemble_staging_prompt, load_catalog


ROOM_TYPES = {'living_diner_room', 'bedroom', 'studio'}


def build_manifest(
    *,
    catalog_path: Path,
    sources_path: Path,
    output_path: Path,
    run_id: str,
    seeds: list[int],
    candidates_path: Path | None,
    include_no_furniture: bool,
    model_version: str,
    inference: dict[str, Any],
) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    sources = _load_sources(sources_path)
    candidates = _load_candidates(candidates_path)
    if candidates is None:
        style_cases = catalog['pilot']['style_cases']
        empty_cases = catalog['pilot']['no_furniture_cases']
    else:
        style_cases = _explicit_style_cases(catalog, candidates.get('style_variant_ids', []))
        empty_cases = _explicit_empty_cases(
            catalog, candidates.get('no_furniture_variant_ids', [])
        )

    cases = []
    for source in sources:
        matching_style_cases = [
            case for case in style_cases if case['room_type'] == source['room_type']
        ]
        matching_empty_cases = [
            case for case in empty_cases if case['room_type'] == source['room_type']
        ]
        for seed in seeds:
            for pilot_case in matching_style_cases:
                prompt = assemble_staging_prompt(
                    catalog, pilot_case['variant_id'], source['room_type'], 'standard'
                )
                cases.append(
                    _run_case(run_id, source, seed, pilot_case['test_case_id'], prompt, inference)
                )
            if include_no_furniture:
                for pilot_case in matching_empty_cases:
                    prompt = assemble_no_furniture_prompt(
                        catalog, pilot_case['variant_id'], source['room_type'], 'standard'
                    )
                    cases.append(
                        _run_case(
                            run_id, source, seed, pilot_case['test_case_id'], prompt, inference
                        )
                    )

    manifest = {
        'schema_version': 1,
        'run_id': run_id,
        'catalog_version': catalog['catalog_version'],
        'catalog_sha256': catalog['source']['sha256'],
        'model_version': model_version,
        'inference': inference,
        'source_count': len(sources),
        'seed_count': len(seeds),
        'case_count': len(cases),
        'cases': cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return manifest


def _load_sources(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    values = payload.get('sources') if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        raise ValueError('Source manifest must contain a non-empty sources array')
    seen = set()
    sources = []
    for value in values:
        if not isinstance(value, dict):
            raise ValueError('Each source must be an object')
        source_id = value.get('source_image_id')
        room_type = value.get('room_type')
        source_path = Path(str(value.get('path', ''))).expanduser().resolve()
        if not isinstance(source_id, str) or not source_id:
            raise ValueError('Each source requires source_image_id')
        if source_id in seen:
            raise ValueError(f'Duplicate source_image_id: {source_id}')
        if room_type not in ROOM_TYPES:
            raise ValueError(f'Invalid room type for {source_id}: {room_type}')
        if not source_path.is_file():
            raise FileNotFoundError(f'Source image does not exist: {source_path}')
        seen.add(source_id)
        sources.append(
            {
                'source_image_id': source_id,
                'room_type': room_type,
                'path': str(source_path),
                'sha256': _sha256_file(source_path),
            }
        )
    return sources


def _load_candidates(path: Path | None) -> dict[str, list[str]] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError('Candidate file must be a JSON object')
    for key in ('style_variant_ids', 'no_furniture_variant_ids'):
        values = payload.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError(f'{key} must be an array of strings')
    return payload


def _explicit_style_cases(
    catalog: dict[str, Any], variant_ids: list[str]
) -> list[dict[str, str]]:
    variants = {variant['variant_id']: variant for variant in catalog['style_variants']}
    missing = set(variant_ids).difference(variants)
    if missing:
        raise ValueError(f'Unknown style candidates: {sorted(missing)}')
    cases = []
    for variant_id in variant_ids:
        variant = variants[variant_id]
        for room_type in sorted(ROOM_TYPES):
            cases.append(
                {
                    'test_case_id': f'CUSTOM-{variant_id}-{room_type}',
                    'variant_id': variant_id,
                    'style_id': variant['style_id'],
                    'room_type': room_type,
                    'benchmark_role': variant['benchmark_role'],
                }
            )
    return cases


def _explicit_empty_cases(
    catalog: dict[str, Any], variant_ids: list[str]
) -> list[dict[str, str]]:
    variants = {
        variant['variant_id']: variant for variant in catalog['no_furniture']['removal_variants']
    }
    missing = set(variant_ids).difference(variants)
    if missing:
        raise ValueError(f'Unknown No Furniture candidates: {sorted(missing)}')
    return [
        {
            'test_case_id': f'CUSTOM-{variant_id}-{room_type}',
            'variant_id': variant_id,
            'style_id': 'empty',
            'room_type': room_type,
            'benchmark_role': variants[variant_id]['benchmark_role'],
        }
        for variant_id in variant_ids
        for room_type in sorted(ROOM_TYPES)
    ]


def _run_case(
    run_id: str,
    source: dict[str, str],
    seed: int,
    pilot_case_id: str,
    prompt: dict[str, Any],
    inference: dict[str, Any],
) -> dict[str, Any]:
    identity = '|'.join(
        [
            run_id,
            source['source_image_id'],
            prompt['variant_id'],
            source['room_type'],
            str(seed),
        ]
    )
    case_id = hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]
    return {
        'case_id': case_id,
        'pilot_case_id': pilot_case_id,
        'source_image_id': source['source_image_id'],
        'source_path': source['path'],
        'source_sha256': source['sha256'],
        'room_type': source['room_type'],
        'mode': prompt['mode'],
        'style_id': prompt['style_id'],
        'style_number': prompt['style_number'],
        'style_name': prompt['style_name'],
        'variant_id': prompt['variant_id'],
        'prompt_ref': prompt['prompt_ref'],
        'anchor_id': prompt['anchor_id'],
        'seed': seed,
        'inference': inference,
        'prompt': prompt['prompt'],
        'prompt_sha256': prompt['prompt_sha256'],
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()
