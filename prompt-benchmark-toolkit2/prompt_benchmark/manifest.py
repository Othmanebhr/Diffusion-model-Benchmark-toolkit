from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .catalog import load_catalog, select_prompts


ROOM_TYPES = {'living_diner_room', 'bedroom', 'studio'}


def build_manifest(
    *,
    catalog_path: Path,
    sources_path: Path,
    output_path: Path,
    run_id: str,
    seeds: list[int],
    candidates_path: Path | None,
    model_version: str,
    inference: dict[str, Any],
) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    sources = _load_sources(sources_path)
    candidate_ids = _load_candidates(candidates_path)
    _validate_candidates(catalog, candidate_ids)

    cases = []
    for source in sources:
        prompts = select_prompts(
            catalog,
            room_type=source['room_type'],
            variant_ids=candidate_ids,
        )
        for seed in seeds:
            for prompt in prompts:
                cases.append(_run_case(run_id, source, seed, prompt, inference))

    if not cases:
        raise ValueError('The selected sources and prompt candidates produced no benchmark cases')

    manifest = {
        'schema_version': 1,
        'run_id': run_id,
        'catalog_version': catalog['catalog_version'],
        'catalog_sha256': catalog['catalog_sha256'],
        'model_version': model_version,
        'inference': inference,
        'source_count': len(sources),
        'seed_count': len(seeds),
        'case_count': len(cases),
        'cases': cases,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
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


def _load_candidates(path: Path | None) -> set[str] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    values = payload.get('variant_ids') if isinstance(payload, dict) else None
    if not isinstance(values, list) or not values:
        raise ValueError('Candidate file must contain a non-empty variant_ids array')
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('variant_ids must contain non-empty strings')
    if len(values) != len(set(values)):
        raise ValueError('variant_ids must not contain duplicates')
    return set(values)


def _validate_candidates(catalog: dict[str, Any], candidate_ids: set[str] | None) -> None:
    if candidate_ids is None:
        return
    available = {prompt['variant_id'] for prompt in catalog['prompts']}
    missing = candidate_ids.difference(available)
    if missing:
        raise ValueError(f'Unknown prompt candidates: {sorted(missing)}')


def _run_case(
    run_id: str,
    source: dict[str, str],
    seed: int,
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
        'source_image_id': source['source_image_id'],
        'source_path': source['path'],
        'source_sha256': source['sha256'],
        'room_type': source['room_type'],
        'mode': prompt['mode'],
        'style_id': prompt['style_id'],
        'style_number': prompt['style_number'],
        'style_name': prompt['style_name'],
        'variant_id': prompt['variant_id'],
        'variant_label': prompt['variant_label'],
        'prompt_ref': prompt['prompt_ref'],
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
