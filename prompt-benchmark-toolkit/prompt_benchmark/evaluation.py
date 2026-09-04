from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any


IDENTITY_COLUMNS = [
    'blind_id',
    'case_id',
    'output_path',
    'source_image_id',
    'room_type',
    'mode',
    'style_id',
    'variant_id',
    'prompt_ref',
    'variant_label',
    'seed',
    'model_version',
    'catalog_version',
]
SCORE_COLUMNS = [
    'style_fidelity',
    'architecture_preservation',
    'camera_perspective',
    'functional_layout',
    'photorealism',
    'artifacts_cleanliness',
    'removal_completeness',
    'hidden_surface_reconstruction',
]
OTHER_COLUMNS = ['structural_violation', 'reviewer', 'notes', 'weighted_score', 'hard_gate_pass']
WEIGHTS = {
    'style_fidelity': 0.15,
    'architecture_preservation': 0.25,
    'camera_perspective': 0.15,
    'functional_layout': 0.10,
    'photorealism': 0.15,
    'artifacts_cleanliness': 0.10,
    'removal_completeness': 0.05,
    'hidden_surface_reconstruction': 0.05,
}


def create_evaluation_template(results_path: Path, output_path: Path) -> int:
    results = [
        json.loads(line)
        for line in results_path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    successful = sorted(
        (result for result in results if result.get('status') == 'succeeded'),
        key=lambda result: hashlib_key(result['case_id']),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(
            handle, fieldnames=IDENTITY_COLUMNS + SCORE_COLUMNS + OTHER_COLUMNS
        )
        writer.writeheader()
        for index, result in enumerate(successful, start=1):
            row = {column: result.get(column, '') for column in IDENTITY_COLUMNS}
            row['blind_id'] = f'B-{index:04d}'
            writer.writerow(row)
    return len(successful)


def score_evaluations(
    *,
    evaluation_path: Path,
    ranking_path: Path,
    finalists_path: Path,
    top_k: int,
) -> dict[str, int]:
    if top_k < 1:
        raise ValueError('top_k must be at least 1')
    with evaluation_path.open('r', encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        scores = _read_scores(row)
        if not scores:
            continue
        weighted = _weighted_score(scores)
        hard_pass = (
            scores.get('architecture_preservation', 0) >= 4
            and scores.get('camera_perspective', 0) >= 4
            and not _truthy(row.get('structural_violation', ''))
        )
        row['weighted_score'] = weighted
        row['hard_gate_pass'] = hard_pass
        grouped[(row['style_id'], row['room_type'], row['variant_id'])].append(row)

    ranking = []
    for (style_id, room_type, variant_id), values in grouped.items():
        ranking.append(
            {
                'style_id': style_id,
                'room_type': room_type,
                'variant_id': variant_id,
                'evaluated_cases': len(values),
                'average_weighted_score': round(
                    mean(float(value['weighted_score']) for value in values), 4
                ),
                'hard_gate_pass_rate': round(
                    sum(bool(value['hard_gate_pass']) for value in values) / len(values), 4
                ),
                'hard_failures': sum(not bool(value['hard_gate_pass']) for value in values),
            }
        )
    ranking.sort(
        key=lambda row: (
            row['style_id'],
            row['room_type'],
            -float(row['hard_gate_pass_rate']),
            -float(row['average_weighted_score']),
            row['variant_id'],
        )
    )

    ranking_path.parent.mkdir(parents=True, exist_ok=True)
    with ranking_path.open('w', encoding='utf-8-sig', newline='') as handle:
        fieldnames = [
            'style_id',
            'room_type',
            'variant_id',
            'evaluated_cases',
            'average_weighted_score',
            'hard_gate_pass_rate',
            'hard_failures',
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ranking)

    by_room: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in ranking:
        if float(row['hard_gate_pass_rate']) == 1.0:
            by_room[row['room_type']].append(row)
    finalists = {
        'variant_ids': [
            row['variant_id']
            for room_type in sorted(by_room)
            for row in by_room[room_type][:top_k]
        ]
    }
    finalists_path.parent.mkdir(parents=True, exist_ok=True)
    finalists_path.write_text(
        json.dumps(finalists, indent=2, ensure_ascii=False) + '\n', encoding='utf-8'
    )
    return {'variant_count': len(ranking)}


def _read_scores(row: dict[str, str]) -> dict[str, float]:
    scores = {}
    for column in SCORE_COLUMNS:
        raw = (row.get(column) or '').strip()
        if not raw:
            continue
        value = float(raw)
        if value < 1 or value > 5:
            raise ValueError(f'{column} must be between 1 and 5')
        scores[column] = value
    return scores


def _weighted_score(scores: dict[str, float]) -> float:
    denominator = sum(WEIGHTS[column] for column in scores)
    return round(sum(scores[column] * WEIGHTS[column] for column in scores) / denominator, 4)


def _truthy(value: str) -> bool:
    return value.strip().lower() in {'1', 'true', 'yes', 'y', 'oui'}


def hashlib_key(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode('utf-8')).hexdigest()
