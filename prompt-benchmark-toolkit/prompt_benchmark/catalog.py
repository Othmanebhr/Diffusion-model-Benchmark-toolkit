from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


CATALOG_VERSION = 'modern-arabic-prompts-30-v1'
STYLE_ID = 'modern_arabic'
STYLE_NUMBER = 1
STYLE_NAME = 'Modern Arabic'
ROOM_SECTIONS = {
    'living_room_prompts': ('living_diner_room', 'LR', 0),
    'bedroom_prompts': ('bedroom', 'BR', 10),
    'studio_prompts': ('studio', 'ST', 20),
}


def load_catalog(path: Path) -> dict[str, Any]:
    """Load the simple user-authored catalog without altering prompt text."""
    raw_bytes = path.read_bytes()
    payload = json.loads(raw_bytes.decode('utf-8'))
    if not isinstance(payload, dict):
        raise ValueError('Prompt catalog must be a JSON object')

    unexpected = set(payload).difference(ROOM_SECTIONS)
    missing = set(ROOM_SECTIONS).difference(payload)
    if missing or unexpected:
        raise ValueError(
            f'Prompt catalog sections mismatch; missing={sorted(missing)}, '
            f'unexpected={sorted(unexpected)}'
        )

    prompts: list[dict[str, Any]] = []
    for section, (room_type, room_code, prompt_offset) in ROOM_SECTIONS.items():
        rows = payload[section]
        if not isinstance(rows, list) or len(rows) != 10:
            raise ValueError(f'{section} must contain exactly 10 prompts')
        seen_ids: set[int] = set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f'Every entry in {section} must be an object')
            prompt_id = row.get('id')
            label = row.get('style')
            prompt = row.get('prompt')
            if not isinstance(prompt_id, int) or prompt_id < 1:
                raise ValueError(f'Every entry in {section} requires a positive integer id')
            if prompt_id in seen_ids:
                raise ValueError(f'Duplicate id {prompt_id} in {section}')
            if not isinstance(label, str) or not label.strip():
                raise ValueError(f'Prompt {prompt_id} in {section} requires a style label')
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f'Prompt {prompt_id} in {section} requires prompt text')
            seen_ids.add(prompt_id)
            prompts.append(
                {
                    'mode': 'staging',
                    'style_id': STYLE_ID,
                    'style_number': STYLE_NUMBER,
                    'style_name': STYLE_NAME,
                    'variant_id': f'MA-{room_code}-P{prompt_id:02d}',
                    'variant_label': label,
                    'prompt_ref': f'P.{STYLE_NUMBER}.{prompt_offset + prompt_id}',
                    'room_type': room_type,
                    'prompt': prompt,
                    'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
                }
            )
        if seen_ids != set(range(1, 11)):
            raise ValueError(f'{section} ids must be exactly 1 through 10')

    return {
        'schema_version': 1,
        'catalog_version': CATALOG_VERSION,
        'catalog_sha256': hashlib.sha256(raw_bytes).hexdigest(),
        'source_file': path.name,
        'prompts': prompts,
    }


def select_prompts(
    catalog: dict[str, Any], *, room_type: str, variant_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    prompts = [prompt for prompt in catalog['prompts'] if prompt['room_type'] == room_type]
    if variant_ids is not None:
        prompts = [prompt for prompt in prompts if prompt['variant_id'] in variant_ids]
    return prompts
