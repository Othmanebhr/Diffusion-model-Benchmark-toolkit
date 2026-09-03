from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


DETAIL_LEVELS = {'micro', 'standard', 'detailed'}


def load_catalog(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as handle:
        catalog = json.load(handle)
    if catalog.get('schema_version') != 1:
        raise ValueError(f"Unsupported catalog schema: {catalog.get('schema_version')}")
    return catalog


def assemble_staging_prompt(
    catalog: dict[str, Any], variant_id: str, room_type: str, detail_level: str = 'standard'
) -> dict[str, Any]:
    _require_detail_level(detail_level)
    variant = _index_by(catalog['style_variants'], 'variant_id').get(variant_id)
    if not variant:
        raise KeyError(f'Unknown style variant: {variant_id}')
    room = catalog['room_types'].get(room_type)
    if not room:
        raise KeyError(f'Unknown room type: {room_type}')
    anchor_key = f"{variant['style_id']}:{variant['cluster_id']}:{room_type}"
    anchor = catalog['furniture_anchors'].get(anchor_key)
    if not anchor:
        raise KeyError(f'Missing furniture anchor: {anchor_key}')

    blocks = [
        catalog['production_guardrails']['master_staging_guardrail'],
        room['blocks'][detail_level],
        variant['blocks'][detail_level],
        anchor['blocks'][detail_level],
    ]
    prompt = '\n\n'.join(block.strip() for block in blocks if block.strip())
    return {
        'mode': 'staging',
        'style_id': variant['style_id'],
        'style_number': variant['style_number'],
        'style_name': variant['style_name'],
        'variant_id': variant['variant_id'],
        'prompt_ref': variant['prompt_ref'],
        'anchor_id': anchor['anchor_id'],
        'room_type': room_type,
        'detail_level': detail_level,
        'prompt': prompt,
        'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
    }


def assemble_no_furniture_prompt(
    catalog: dict[str, Any], removal_script_id: str, room_type: str, detail_level: str = 'standard'
) -> dict[str, Any]:
    _require_detail_level(detail_level)
    variant = _index_by(catalog['no_furniture']['removal_variants'], 'variant_id').get(
        removal_script_id
    )
    if not variant:
        raise KeyError(f'Unknown No Furniture variant: {removal_script_id}')
    room_context = catalog['no_furniture']['room_contexts'].get(room_type)
    if not room_context:
        raise KeyError(f'Unknown No Furniture room type: {room_type}')

    blocks = [
        catalog['production_guardrails']['master_no_furniture_guardrail'],
        room_context,
        variant['blocks'][detail_level],
    ]
    prompt = '\n\n'.join(block.strip() for block in blocks if block.strip())
    return {
        'mode': 'no_furniture',
        'style_id': 'empty',
        'style_number': 7,
        'style_name': 'No Furniture',
        'variant_id': variant['variant_id'],
        'prompt_ref': variant['prompt_ref'],
        'anchor_id': '',
        'room_type': room_type,
        'detail_level': detail_level,
        'prompt': prompt,
        'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
    }


def _index_by(values: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {value[key]: value for value in values}


def _require_detail_level(detail_level: str) -> None:
    if detail_level not in DETAIL_LEVELS:
        raise ValueError(f"detail_level must be one of {sorted(DETAIL_LEVELS)}")

