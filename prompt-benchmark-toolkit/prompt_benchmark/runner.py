from __future__ import annotations

import asyncio
import base64
import importlib
import inspect
import json
import time
from pathlib import Path
from typing import Any, Callable


Adapter = Callable[[dict[str, Any]], Any]


def run_manifest(
    *,
    manifest_path: Path,
    output_dir: Path,
    adapter_spec: str | None,
    dry_run: bool,
    limit: int | None,
) -> dict[str, int]:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('cases'), list):
        raise ValueError('Unsupported or invalid run manifest')
    if not dry_run and not adapter_spec:
        raise ValueError('--adapter is required unless --dry-run is used')

    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / 'results.jsonl'
    completed = _successful_case_ids(results_path)
    adapter = None if dry_run else _load_adapter(adapter_spec or '')
    cases = manifest['cases'][:limit] if limit is not None else manifest['cases']
    summary = {'succeeded': 0, 'failed': 0, 'skipped': 0}

    for index, case in enumerate(cases, start=1):
        case_id = case['case_id']
        if case_id in completed:
            summary['skipped'] += 1
            continue
        print(f"[{index}/{len(cases)}] {case_id} {case['variant_id']} {case['source_image_id']}")
        started = time.monotonic()
        try:
            if dry_run:
                result = {
                    'case_id': case_id,
                    'status': 'dry_run',
                    'prompt_sha256': case['prompt_sha256'],
                    'prompt': case['prompt'],
                }
            else:
                generated = _invoke_adapter(adapter, _adapter_request(manifest, case))
                image_bytes, extension, metadata = _normalize_adapter_result(generated)
                _validate_image(image_bytes)
                output_path = output_dir / 'images' / f'{case_id}{extension}'
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(image_bytes)
                result = {
                    'case_id': case_id,
                    'status': 'succeeded',
                    'output_path': str(output_path.resolve()),
                    'duration_seconds': round(time.monotonic() - started, 3),
                    'metadata': metadata,
                    **_result_identity(manifest, case),
                }
                summary['succeeded'] += 1
        except Exception as error:  # benchmark must record failures and continue
            result = {
                'case_id': case_id,
                'status': 'failed',
                'duration_seconds': round(time.monotonic() - started, 3),
                'error_type': type(error).__name__,
                'error': str(error),
                **_result_identity(manifest, case),
            }
            summary['failed'] += 1
        _append_jsonl(results_path, result)
    return summary


def _adapter_request(manifest: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    return {
        **case,
        'run_id': manifest['run_id'],
        'catalog_version': manifest['catalog_version'],
        'model_version': manifest['model_version'],
    }


def _result_identity(manifest: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    keys = (
        'pilot_case_id',
        'source_image_id',
        'source_path',
        'source_sha256',
        'room_type',
        'mode',
        'style_id',
        'style_number',
        'style_name',
        'variant_id',
        'prompt_ref',
        'anchor_id',
        'seed',
        'inference',
        'prompt_sha256',
    )
    return {
        'run_id': manifest['run_id'],
        'catalog_version': manifest['catalog_version'],
        'model_version': manifest['model_version'],
        **{key: case.get(key) for key in keys},
    }


def _load_adapter(spec: str) -> Adapter:
    if ':' not in spec:
        raise ValueError('Adapter must use module:function syntax')
    module_name, function_name = spec.rsplit(':', 1)
    module = importlib.import_module(module_name)
    function = getattr(module, function_name, None)
    if not callable(function):
        raise ValueError(f'Adapter callable not found: {spec}')
    return function


def _invoke_adapter(adapter: Adapter | None, request: dict[str, Any]) -> Any:
    if adapter is None:
        raise RuntimeError('Model adapter is not configured')
    value = adapter(request)
    if inspect.isawaitable(value):
        return asyncio.run(value)
    return value


def _normalize_adapter_result(value: Any) -> tuple[bytes, str, dict[str, Any]]:
    if isinstance(value, bytes):
        return value, _extension_from_magic(value), {}
    if isinstance(value, (str, Path)):
        path = Path(value)
        return path.read_bytes(), path.suffix.lower() or '.png', {'adapter_output_path': str(path)}
    if not isinstance(value, dict):
        raise TypeError('Adapter must return bytes, a path, or a result object')
    metadata = value.get('metadata', {})
    if not isinstance(metadata, dict):
        raise TypeError('Adapter metadata must be an object')
    if isinstance(value.get('image_bytes'), bytes):
        image_bytes = value['image_bytes']
    elif isinstance(value.get('image_base64'), str):
        image_bytes = base64.b64decode(value['image_base64'], validate=True)
    elif isinstance(value.get('output_path'), (str, Path)):
        path = Path(value['output_path'])
        image_bytes = path.read_bytes()
        metadata = {**metadata, 'adapter_output_path': str(path)}
    else:
        raise TypeError('Adapter result requires image_bytes, image_base64, or output_path')
    extension = str(value.get('extension') or _extension_from_magic(image_bytes)).lower()
    if not extension.startswith('.'):
        extension = f'.{extension}'
    return image_bytes, extension, metadata


def _validate_image(value: bytes) -> None:
    _extension_from_magic(value)


def _extension_from_magic(value: bytes) -> str:
    if value.startswith(b'\x89PNG\r\n\x1a\n'):
        return '.png'
    if value.startswith(b'\xff\xd8\xff'):
        return '.jpg'
    if value.startswith(b'RIFF') and value[8:12] == b'WEBP':
        return '.webp'
    raise ValueError('Adapter output is not a PNG, JPEG, or WebP image')


def _successful_case_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    successful = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if value.get('status') == 'succeeded':
            successful.add(value['case_id'])
    return successful


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + '\n')

