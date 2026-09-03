from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .catalog import assemble_no_furniture_prompt, assemble_staging_prompt


MAIN_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PACKAGE_REL_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'
NS = {'x': MAIN_NS, 'r': REL_NS, 'pr': PACKAGE_REL_NS}

STYLE_MAPPING = {
    'Modern Arabic': ('modern_arabic', 1, 'MA'),
    'Traditional Arabic': ('traditional_arabic', 2, 'TA'),
    'Modern Indian': ('modern_indian', 3, 'MI'),
    'Traditional Indian': ('traditional_indian', 4, 'TI'),
    'Modern': ('modern', 5, 'MO'),
    'Coastal': ('coastal', 6, 'CO'),
}
ROOM_MAPPING = {
    'Living-Dining Room': 'living_diner_room',
    'Bedroom': 'bedroom',
    'Studio': 'studio',
}


def compile_workbook(
    workbook_path: Path, output_path: Path, report_path: Path, catalog_version: str = 'v3'
) -> dict[str, Any]:
    workbook_path = workbook_path.resolve()
    sheets = _read_xlsx(workbook_path)
    required = {
        'Room Type Modules',
        'Style Variant Modules',
        'Furniture Anchors',
        'No Furniture Removal',
        'Product Policies',
        'Production Guardrails',
        'Pilot Matrix Styles',
        'Pilot Matrix No Furniture',
        'Evaluation Template',
    }
    missing = required.difference(sheets)
    if missing:
        raise ValueError(f'Missing workbook sheets: {sorted(missing)}')

    room_types = _compile_room_types(sheets['Room Type Modules'])
    style_variants = _compile_style_variants(sheets['Style Variant Modules'])
    anchors = _compile_anchors(sheets['Furniture Anchors'])
    guardrails = _compile_guardrails(sheets['Production Guardrails'])
    no_furniture_variants = _compile_no_furniture_variants(sheets['No Furniture Removal'])
    no_furniture_contexts = _compile_no_furniture_contexts(sheets['Pilot Matrix No Furniture'])
    style_pilot = _compile_style_pilot(sheets['Pilot Matrix Styles'])
    no_furniture_pilot = _compile_no_furniture_pilot(sheets['Pilot Matrix No Furniture'])

    catalog: dict[str, Any] = {
        'schema_version': 1,
        'catalog_version': catalog_version,
        'source': {
            'file_name': workbook_path.name,
            'sha256': _sha256_file(workbook_path),
        },
        'style_mapping': {
            style_id: {'number': number, 'display_name': display_name}
            for display_name, (style_id, number, _) in STYLE_MAPPING.items()
        }
        | {'empty': {'number': 7, 'display_name': 'No Furniture'}},
        'production_guardrails': guardrails,
        'product_policies': _records(sheets['Product Policies']),
        'room_types': room_types,
        'style_variants': style_variants,
        'furniture_anchors': anchors,
        'no_furniture': {
            'removal_variants': no_furniture_variants,
            'room_contexts': no_furniture_contexts,
        },
        'pilot': {
            'style_cases': style_pilot,
            'no_furniture_cases': no_furniture_pilot,
        },
        'evaluation': {
            'weights': _evaluation_weights(sheets['Evaluation Template']),
            'hard_gates': {
                'architecture_preservation_min': 4,
                'camera_perspective_min': 4,
            },
        },
    }

    mismatches = _validate_catalog(catalog, sheets)
    report = {
        'catalog_version': catalog_version,
        'source_sha256': catalog['source']['sha256'],
        'room_type_count': len(room_types),
        'style_count': len(STYLE_MAPPING),
        'style_variant_count': len(style_variants),
        'furniture_anchor_count': len(anchors),
        'no_furniture_variant_count': len(no_furniture_variants),
        'style_pilot_case_count': len(style_pilot),
        'no_furniture_pilot_case_count': len(no_furniture_pilot),
        'assembled_prompt_mismatches': mismatches,
        'valid': not mismatches,
    }
    if mismatches:
        raise ValueError(f'Catalog validation failed with {len(mismatches)} prompt mismatches')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return report


def _read_xlsx(path: Path) -> dict[str, list[dict[str, str]]]:
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        relations = ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets = {
            relation.attrib['Id']: relation.attrib['Target'].lstrip('/')
            for relation in relations.findall('pr:Relationship', NS)
        }
        shared_strings = _shared_strings(archive)
        result: dict[str, list[dict[str, str]]] = {}
        for sheet in workbook.findall('x:sheets/x:sheet', NS):
            relation_id = sheet.attrib[f'{{{REL_NS}}}id']
            target = targets[relation_id]
            if not target.startswith('xl/'):
                target = f'xl/{target}'
            result[sheet.attrib['name']] = _read_sheet(archive.read(target), shared_strings)
        return result


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if 'xl/sharedStrings.xml' not in archive.namelist():
        return []
    root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
    return [''.join(node.text or '' for node in item.findall('.//x:t', NS)) for item in root.findall('x:si', NS)]


def _read_sheet(xml: bytes, shared_strings: list[str]) -> list[dict[str, str]]:
    root = ET.fromstring(xml)
    rows: list[dict[str, str]] = []
    for row in root.findall('.//x:sheetData/x:row', NS):
        values: dict[str, str] = {}
        for cell in row.findall('x:c', NS):
            match = re.match(r'([A-Z]+)', cell.attrib['r'])
            if not match:
                continue
            column = match.group(1)
            value_node = cell.find('x:v', NS)
            value = '' if value_node is None or value_node.text is None else value_node.text
            if cell.attrib.get('t') == 's' and value:
                value = shared_strings[int(value)]
            elif cell.attrib.get('t') == 'inlineStr':
                value = ''.join(node.text or '' for node in cell.findall('.//x:t', NS))
            formula = cell.find('x:f', NS)
            if formula is not None and formula.text:
                values[f'{column}__formula'] = formula.text
            values[column] = value
        rows.append(values)
    return rows


def _records(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return []
    headers = {column: value.strip() for column, value in rows[0].items() if '__' not in column}
    records = []
    for row in rows[1:]:
        record = {header: row.get(column, '').strip() for column, header in headers.items()}
        if any(record.values()):
            records.append(record)
    return records


def _compile_room_types(rows: list[dict[str, str]]) -> dict[str, Any]:
    room_types = {}
    for record in _records(rows):
        room_type = ROOM_MAPPING[record['Room Type']]
        room_types[room_type] = {
            'module_id': record['Room Module ID'],
            'display_name': record['Room Type'],
            'blocks': {
                'micro': record['Micro Room Block'],
                'standard': record['Standard Room Block'],
                'detailed': record['Detailed Room Block'],
            },
        }
    return room_types


def _compile_style_variants(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    variants = []
    for record in _records(rows):
        style_id, style_number, expected_prefix = STYLE_MAPPING[record['Style']]
        match = re.fullmatch(r'([A-Z]{2})-P(\d{2})', record['Variant ID'])
        if not match or match.group(1) != expected_prefix:
            raise ValueError(f"Invalid variant ID: {record['Variant ID']}")
        prompt_index = int(match.group(2))
        variants.append(
            {
                'variant_id': record['Variant ID'],
                'prompt_ref': f'P.{style_number}.{prompt_index}',
                'style_id': style_id,
                'style_number': style_number,
                'style_name': record['Style'],
                'cluster_id': record['Cluster ID'],
                'cluster_theme': record['Cluster Theme'],
                'variant_name': record['Variant'],
                'benchmark_role': _snake(record['Benchmark Role']),
                'palette': record['Palette'],
                'materials': record['Materials'],
                'movable_decor': record['Movable Decor'],
                'blocks': {
                    'micro': record['Micro Style Block'],
                    'standard': record['Standard Style Block'],
                    'detailed': record['Detailed Style Block'],
                },
            }
        )
    return variants


def _compile_anchors(rows: list[dict[str, str]]) -> dict[str, Any]:
    anchors = {}
    for record in _records(rows):
        style_id = STYLE_MAPPING[record['Style']][0]
        room_type = ROOM_MAPPING[record['Room Type']]
        key = f"{style_id}:{record['Cluster ID']}:{room_type}"
        if key in anchors:
            raise ValueError(f'Duplicate furniture anchor: {key}')
        anchors[key] = {
            'anchor_id': record['Anchor ID'],
            'style_id': style_id,
            'cluster_id': record['Cluster ID'],
            'cluster_theme': record['Cluster Theme'],
            'room_type': room_type,
            'furniture_anchor_list': record['Furniture Anchor List'],
            'blocks': {
                'micro': record['Micro Anchor Block'],
                'standard': record['Standard Anchor Block'],
                'detailed': record['Detailed Anchor Block'],
            },
        }
    return anchors


def _compile_guardrails(rows: list[dict[str, str]]) -> dict[str, str]:
    records = _records(rows)
    lookup = {record['Guardrail']: record['Text'] for record in records}
    return {
        'master_staging_guardrail': lookup['Master Staging Guardrail'],
        'master_no_furniture_guardrail': lookup['Master No Furniture Guardrail'],
        'no_furniture_semi_fixed_policy': lookup['No Furniture Semi-fixed Policy'],
    }


def _compile_no_furniture_variants(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    variants = []
    for record in _records(rows):
        match = re.fullmatch(r'NF-P(\d{2})', record['Script ID'])
        if not match:
            raise ValueError(f"Invalid No Furniture script ID: {record['Script ID']}")
        variants.append(
            {
                'variant_id': record['Script ID'],
                'prompt_ref': f"P.7.{int(match.group(1))}",
                'group': record['Group'],
                'theme': record['Theme'],
                'variant_name': record['Variant'],
                'benchmark_role': _snake(record['Benchmark Role']),
                'blocks': {
                    'micro': record['Micro Removal Block'],
                    'standard': record['Standard Removal Block'],
                    'detailed': record['Detailed Removal Block'],
                },
            }
        )
    return variants


def _compile_no_furniture_contexts(rows: list[dict[str, str]]) -> dict[str, str]:
    contexts = {}
    for record in _records(rows):
        room_type = ROOM_MAPPING[record['Room Type']]
        contexts.setdefault(room_type, record['Room Context Module'])
        if contexts[room_type] != record['Room Context Module']:
            raise ValueError(f'No Furniture room context varies for {room_type}')
    return contexts


def _compile_style_pilot(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    cases = []
    for record in _records(rows):
        style_id, _, _ = STYLE_MAPPING[record['Style']]
        cases.append(
            {
                'test_case_id': record['Test Case ID'],
                'variant_id': record['Variant ID'],
                'style_id': style_id,
                'room_type': ROOM_MAPPING[record['Room Type']],
                'anchor_id': record['Anchor ID'],
                'benchmark_role': _snake(record['Benchmark Role']),
            }
        )
    return cases


def _compile_no_furniture_pilot(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            'test_case_id': record['Test Case ID'],
            'variant_id': record['Removal Script ID'],
            'style_id': 'empty',
            'room_type': ROOM_MAPPING[record['Room Type']],
            'benchmark_role': _snake(record['Benchmark Role']),
        }
        for record in _records(rows)
    ]


def _evaluation_weights(rows: list[dict[str, str]]) -> dict[str, float]:
    if len(rows) < 2:
        raise ValueError('Evaluation Template does not contain a formula row')
    formula = rows[1].get('U__formula', '')
    column_names = {
        'K': 'style_fidelity',
        'L': 'architecture_preservation',
        'M': 'camera_perspective',
        'N': 'functional_layout',
        'O': 'photorealism',
        'P': 'artifacts_cleanliness',
        'Q': 'removal_completeness',
        'R': 'hidden_surface_reconstruction',
    }
    weights = {}
    for column, name in column_names.items():
        match = re.search(rf'IF\({column}2="",0,{column}2\)\*([0-9.]+)', formula)
        if not match:
            raise ValueError(f'Unable to read evaluation weight for column {column}')
        weights[name] = float(match.group(1))
    return weights


def _validate_catalog(catalog: dict[str, Any], sheets: dict[str, list[dict[str, str]]]) -> list[str]:
    style_counts = {style_id: 0 for style_id, _, _ in STYLE_MAPPING.values()}
    for variant in catalog['style_variants']:
        style_counts[variant['style_id']] += 1
        for room_type in catalog['room_types']:
            key = f"{variant['style_id']}:{variant['cluster_id']}:{room_type}"
            if key not in catalog['furniture_anchors']:
                raise ValueError(f'Missing anchor coverage: {key}')
    if any(count != 30 for count in style_counts.values()):
        raise ValueError(f'Expected 30 variants per style, got {style_counts}')
    if len(catalog['room_types']) != 3:
        raise ValueError('Expected exactly 3 room types')
    if len(catalog['furniture_anchors']) != 108:
        raise ValueError('Expected exactly 108 furniture anchors')

    mismatches = []
    expected_style = {
        record['Test Case ID']: record['Assembled Standard Instruction']
        for record in _records(sheets['Pilot Matrix Styles'])
    }
    for case in catalog['pilot']['style_cases']:
        assembled = assemble_staging_prompt(
            catalog, case['variant_id'], case['room_type'], 'standard'
        )['prompt']
        if assembled != expected_style[case['test_case_id']]:
            mismatches.append(case['test_case_id'])

    expected_empty = {
        record['Test Case ID']: record['Assembled Standard Instruction']
        for record in _records(sheets['Pilot Matrix No Furniture'])
    }
    for case in catalog['pilot']['no_furniture_cases']:
        assembled = assemble_no_furniture_prompt(
            catalog, case['variant_id'], case['room_type'], 'standard'
        )['prompt']
        if assembled != expected_empty[case['test_case_id']]:
            mismatches.append(case['test_case_id'])
    return mismatches


def _snake(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', value.strip().lower()).strip('_')


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

