import csv
import hashlib
import json
import logging
import math
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .scraper import StatbankScraper

logger = logging.getLogger(__name__)

CKAN_URL = 'https://data.opendata.am'
ORGANIZATION = 'opendataam'
GROUP = 'statistics'
LICENSE_ID = 'other-pd'
RESOURCE_TYPES = (
    {
        'key': 'csv',
        'source_format': 'csv',
        'extension': 'csv',
        'format': 'CSV',
        'mimetype': 'text/csv',
        'description': 'Tabular CSV export with table dimensions and values',
    },
    {
        'key': 'xlsx',
        'source_format': 'excel',
        'extension': 'xlsx',
        'format': 'XLSX',
        'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'description': 'Excel workbook with table values and source metadata',
    },
    {
        'key': 'json-stat2',
        'source_format': 'json-stat2',
        'extension': 'json',
        'format': 'JSON-stat 2',
        'mimetype': 'application/json',
        'description': 'JSON-stat 2 dataset with dimensions, units, values, and missing-value statuses',
    },
)


class CKANError(RuntimeError):
    pass


class CKANClient:
    def __init__(self, token, base_url=CKAN_URL, timeout=(10, 60)):
        if not token:
            raise ValueError('CKAN_API_TOKEN environment variable is required')
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({'Authorization': token})
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(('GET',)),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)

    def _action(
        self,
        action,
        data=None,
        files=None,
        allow_not_found=False,
        method='POST',
    ):
        url = f'{self.base_url}/api/3/action/{action}'
        if method == 'GET':
            response = self.session.get(url, params=data, timeout=self.timeout)
        else:
            response = self.session.post(
                url,
                json=data if files is None else None,
                data=data if files is not None else None,
                files=files,
                timeout=self.timeout,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            if response.ok:
                raise CKANError(f'{action} returned invalid JSON') from exc
            payload = None

        if allow_not_found and response.status_code == 404:
            return None
        if not response.ok:
            error = payload.get('error') if isinstance(payload, dict) else None
            raise CKANError(
                f'{action} failed with HTTP {response.status_code}: {error or "no CKAN error details"}'
            )
        if not isinstance(payload, dict) or not payload.get('success'):
            error = payload.get('error') if isinstance(payload, dict) else payload
            raise CKANError(f'{action} failed: {error}')
        return payload['result']

    def ensure_can_create_datasets(self, organization=ORGANIZATION):
        organizations = self._action(
            'organization_list_for_user',
            {'permission': 'create_dataset'},
            method='GET',
        )
        if not any(
            organization in (item.get('id'), item.get('name'))
            for item in organizations
        ):
            raise CKANError(
                f'Token does not grant dataset creation in organization {organization}'
            )

    def package_show(self, name):
        return self._action(
            'package_show',
            {'id': name},
            allow_not_found=True,
            method='GET',
        )

    def package_create(self, metadata):
        return self._action('package_create', metadata)

    def package_patch(self, package_id, metadata):
        return self._action('package_patch', {
            'id': package_id,
            'notes': metadata['notes'],
            'extras': metadata['extras'],
        })

    def resource_upload(
        self,
        package_id,
        file_path,
        resource_name,
        description,
        sha256,
        resource_id=None,
        resource_format='CSV',
        mimetype='text/csv',
    ):
        data = {
            'package_id': package_id,
            'name': resource_name,
            'description': description,
            'format': resource_format,
            'mimetype': mimetype,
            'hash': sha256,
            'url': resource_name,
        }
        action = 'resource_create'
        if resource_id:
            action = 'resource_update'
            data['id'] = resource_id
        with Path(file_path).open('rb') as upload:
            return self._action(
                action,
                data,
                files={'upload': (resource_name, upload, mimetype)},
            )


def load_indicators(path):
    indicators = []
    seen_urls = set()
    with Path(path).open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                indicator = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Invalid JSON on line {line_number}: {exc}') from exc
            missing = {'id', 'title', 'url', 'topic', 'subtopics'} - indicator.keys()
            if missing:
                raise ValueError(
                    f'Missing fields on line {line_number}: {", ".join(sorted(missing))}'
                )
            if indicator['url'] in seen_urls:
                raise ValueError(f'Duplicate source URL on line {line_number}')
            seen_urls.add(indicator['url'])
            indicators.append(indicator)
    if not indicators:
        raise ValueError('No indicators found')
    return indicators


def dataset_name(indicator):
    slug = re.sub(r'[^a-z0-9]+', '-', indicator['id'].lower()).strip('-')
    slug = slug or 'table'
    digest = hashlib.sha256(indicator['url'].encode('utf-8')).hexdigest()[:10]
    slug = slug[:81].rstrip('-')
    return f'armstat-{slug}-{digest}'


def resource_name(indicator, extension='csv'):
    return f'{dataset_name(indicator)}.{extension}'


def _category_labels(dimension):
    category = dimension.get('category', {})
    index = category.get('index', {})
    labels = category.get('label', {})
    if isinstance(index, dict):
        codes = sorted(index, key=index.get)
    elif isinstance(index, list):
        codes = index
    else:
        codes = []
    result = []
    for position, code in enumerate(codes):
        if isinstance(labels, dict):
            result.append(str(labels.get(code, code)))
        elif isinstance(labels, list) and position < len(labels):
            result.append(str(labels[position]))
        else:
            result.append(str(code))
    return result


def _dimension_units(dimension):
    units = dimension.get('category', {}).get('unit', {})
    if isinstance(units, list):
        units = {str(index): unit for index, unit in enumerate(units)}
    result = []
    for unit in units.values():
        if not isinstance(unit, dict):
            continue
        base = unit.get('base')
        label = unit.get('label')
        value = label or base
        if not value or value == '-':
            continue
        if label and base and label != base:
            value = f'{label} ({base})'
        if unit.get('decimals') is not None:
            value = f'{value}, {unit["decimals"]} decimals'
        if value not in result:
            result.append(value)
    return result


def _csv_shape(path):
    row_count = 0
    column_count = None
    with Path(path).open(encoding='utf-8-sig', newline='') as source:
        for index, row in enumerate(csv.reader(source)):
            if index == 2:
                column_count = len(row)
            elif index > 2 and any(cell for cell in row):
                row_count += 1
    if column_count is None:
        raise ValueError(f'CSV file has no header row: {path}')
    return row_count, column_count


def _basic_notes(indicator):
    notes = [
        'Source: Statistical Committee of the Republic of Armenia (ArmStat), Statbank.',
        f'Table ID: {indicator["id"]}',
        f'Topic: {indicator["topic"]}',
    ]
    if indicator['subtopics']:
        notes.append(f'Subtopics: {" / ".join(indicator["subtopics"])}')
    notes.append(f'Original table: {indicator["url"]}')
    return '\n'.join(notes)


def _rich_notes(indicator, dataset, csv_path):
    px_metadata = dataset.get('extension', {}).get('px', {})
    matrix = px_metadata.get('matrix', indicator['id'])
    topic = ' / '.join([indicator['topic']] + indicator['subtopics'])
    notes = [
        '## Contents',
        '',
        dataset.get('label') or indicator['title'],
        '',
        f'- **ArmStat matrix:** `{matrix}`',
        f'- **Topic:** {topic}',
    ]
    if dataset.get('updated'):
        notes.append(f'- **Source updated:** {dataset["updated"]}')
    if px_metadata.get('subject-area'):
        notes.append(f'- **Statbank subject area:** {px_metadata["subject-area"]}')

    dimension_ids = dataset.get('id', [])
    sizes = dataset.get('size', [])
    cell_count = math.prod(sizes)
    notes.extend([
        '',
        '## Data structure',
        '',
        f'The full dataset contains **{cell_count:,} cells** across **{len(dimension_ids)} dimensions**.',
        '',
    ])
    time_dimensions = set(dataset.get('role', {}).get('time', []))
    for dimension_id, size in zip(dimension_ids, sizes):
        dimension = dataset['dimension'][dimension_id]
        label = dimension.get('label') or dimension_id
        details = [f'{size} categories']
        labels = _category_labels(dimension)
        is_time = dimension_id in time_dimensions or any(
            token in dimension_id.lower()
            for token in ('year', 'month', 'quarter', 'week', 'date', 'time')
        )
        if labels and is_time:
            details.append(f'period: {labels[0]}–{labels[-1]}')
        elif labels:
            examples = ', '.join(labels[:3])
            if size > 3:
                examples += ', …'
            details.append(f'examples: {examples}')
        units = _dimension_units(dimension)
        if units:
            details.append(f'unit: {"; ".join(units)}')
        notes.append(f'- **{label}** (`{dimension_id}`): {"; ".join(details)}.')

    row_count, column_count = _csv_shape(csv_path)
    notes.extend([
        '',
        f'The CSV resource contains **{row_count:,} data rows** and **{column_count} columns**, including dimension columns. The first row is the table title; the third row contains column headings.',
        '',
        '## Resources',
        '',
        '- **CSV:** tabular data for spreadsheets and programmatic processing.',
        '- **XLSX:** Excel workbook with values and source metadata.',
        '- **JSON-stat 2:** structured values, dimensions, units, and missing-value statuses.',
        '',
        '## Source',
        '',
        'Statistical Committee of the Republic of Armenia (ArmStat), Statbank.',
        f'[Original Statbank table]({quote(indicator["url"], safe=":/?&=%")}).',
    ])
    return '\n'.join(notes)


def package_metadata(
    indicator,
    organization=ORGANIZATION,
    dataset=None,
    csv_path=None,
):
    if dataset is not None and csv_path is not None:
        notes = _rich_notes(indicator, dataset, csv_path)
    else:
        notes = _basic_notes(indicator)
    extras = [
        {'key': 'statbank_table_id', 'value': indicator['id']},
        {'key': 'topic', 'value': indicator['topic']},
        {
            'key': 'subtopics',
            'value': json.dumps(indicator['subtopics'], ensure_ascii=False),
        },
    ]
    if dataset is not None and csv_path is not None:
        row_count, column_count = _csv_shape(csv_path)
        dimensions = [
            {
                'id': dimension_id,
                'label': dataset['dimension'][dimension_id].get('label') or dimension_id,
                'size': size,
            }
            for dimension_id, size in zip(dataset.get('id', []), dataset.get('size', []))
        ]
        extras.extend([
            {'key': 'source_updated', 'value': dataset.get('updated', '')},
            {'key': 'cell_count', 'value': str(math.prod(dataset.get('size', [])))},
            {'key': 'csv_rows', 'value': str(row_count)},
            {'key': 'csv_columns', 'value': str(column_count)},
            {'key': 'dimensions', 'value': json.dumps(dimensions, ensure_ascii=False)},
        ])
    return {
        'name': dataset_name(indicator),
        'title': indicator['title'],
        'notes': notes,
        'url': indicator['url'],
        'private': False,
        'owner_org': organization,
        'license_id': LICENSE_ID,
        'groups': [{'name': GROUP}],
        'tags': [{'name': tag} for tag in ('armenia', 'armstat', 'statbank')],
        'extras': extras,
    }


def _metadata_needs_update(package, metadata):
    if package.get('notes') != metadata['notes']:
        return True
    existing = {
        item.get('key'): item.get('value')
        for item in package.get('extras', [])
    }
    return any(
        existing.get(item['key']) != item['value']
        for item in metadata['extras']
    )


def _validate_existing_package(package, indicator, organization):
    if package.get('url') != indicator['url']:
        raise CKANError(
            f'Existing dataset {package["name"]} belongs to a different source URL'
        )
    package_organization = package.get('organization') or {}
    owners = {
        package.get('owner_org'),
        package_organization.get('id'),
        package_organization.get('name'),
    }
    if organization not in owners:
        raise CKANError(
            f'Existing dataset {package["name"]} belongs to another organization'
        )
    if package.get('private'):
        raise CKANError(f'Existing dataset {package["name"]} is private')


def _download_resource(scraper, indicator, destination, file_format):
    content = scraper.get_table_data(indicator['url'], file_format=file_format)
    if not content or not content.strip():
        raise ValueError(f'Source returned an empty file for {indicator["url"]}')
    temporary = destination.with_suffix(destination.suffix + '.part')
    temporary.write_bytes(content)
    os.replace(temporary, destination)


def _report(report_path, result):
    with Path(report_path).open('a', encoding='utf-8') as output:
        output.write(json.dumps(result, ensure_ascii=False) + '\n')


def _publish_indicator(indicator, client, data_dir, scraper, organization):
    name = dataset_name(indicator)
    package = client.package_show(name)
    if package:
        _validate_existing_package(package, indicator, organization)

    prepared = {}
    for resource_type in RESOURCE_TYPES:
        destination = data_dir / resource_name(indicator, resource_type['extension'])
        if not destination.exists():
            _download_resource(
                scraper,
                indicator,
                destination,
                resource_type['source_format'],
            )
        prepared[resource_type['key']] = {
            'path': destination,
            'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
            'size': destination.stat().st_size,
        }
    dataset = json.loads(prepared['json-stat2']['path'].read_bytes())
    metadata = package_metadata(
        indicator,
        organization,
        dataset=dataset,
        csv_path=prepared['csv']['path'],
    )

    existing_resources = {}
    for resource_type in RESOURCE_TYPES:
        expected_name = resource_name(indicator, resource_type['extension'])
        matches = [
            resource
            for resource in (package or {}).get('resources', [])
            if resource.get('name') == expected_name
        ]
        if len(matches) > 1:
            raise CKANError(
                f'Existing dataset {name} has duplicate resources named {expected_name}'
            )
        existing_resources[resource_type['key']] = matches

    created = package is None
    metadata_updated = False
    if created:
        package = client.package_create(metadata)
    elif _metadata_needs_update(package, metadata):
        package = client.package_patch(package['id'], metadata)
        metadata_updated = True

    resource_results = []
    for resource_type in RESOURCE_TYPES:
        key = resource_type['key']
        files = prepared[key]
        expected_name = resource_name(indicator, resource_type['extension'])
        matches = existing_resources[key]
        if matches and matches[0].get('hash') == files['sha256']:
            resource = matches[0]
            resource_status = 'unchanged'
        else:
            resource = client.resource_upload(
                package_id=package['id'],
                file_path=files['path'],
                resource_name=expected_name,
                description=f'{resource_type["description"]}. ArmStat table {indicator["id"]}.',
                sha256=files['sha256'],
                resource_id=matches[0]['id'] if matches else None,
                resource_format=resource_type['format'],
                mimetype=resource_type['mimetype'],
            )
            resource_status = 'updated' if matches else 'created'
        resource_results.append({
            'key': key,
            'id': resource['id'],
            'name': expected_name,
            'url': resource.get('url'),
            'format': resource_type['format'],
            'status': resource_status,
            'sha256': files['sha256'],
            'size': files['size'],
        })

    resources_changed = any(
        resource['status'] != 'unchanged'
        for resource in resource_results
    )
    if created:
        status = 'created'
    elif metadata_updated or resources_changed:
        status = 'updated'
    else:
        status = 'unchanged'
    csv_resource = resource_results[0]
    return {
        'status': status,
        'metadata_updated': metadata_updated,
        'resources': resource_results,
        'sha256': csv_resource['sha256'],
        'size': csv_resource['size'],
        'resource_id': csv_resource['id'],
        'resource_url': csv_resource['url'],
    }


def publish_indicators(
    indicators,
    client,
    data_dir='exports',
    report_path='publish-report.jsonl',
    scraper=None,
    organization=ORGANIZATION,
    delay=0.2,
):
    scraper = scraper or StatbankScraper()
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, indicator in enumerate(indicators, 1):
        name = dataset_name(indicator)
        result = {
            'source_url': indicator['url'],
            'dataset': name,
            'dataset_url': f'{client.base_url}/dataset/{name}',
        }
        try:
            result.update(_publish_indicator(
                indicator,
                client,
                data_dir,
                scraper,
                organization,
            ))
        except Exception as exc:
            result.update({'status': 'error', 'error': str(exc)})
        _report(report_path, result)
        results.append(result)
        logger.info(
            '[%d/%d] %s: %s',
            index,
            len(indicators),
            name,
            result['status'],
        )
        if delay and index < len(indicators):
            time.sleep(delay)
    return results
