import hashlib
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from click.testing import CliRunner

from statbank_parser.ckan import (
    CKANClient,
    CKANError,
    RESOURCE_TYPES,
    dataset_name,
    package_metadata,
    publish_indicators,
    resource_name,
)
from statbank_parser.cli import cli


INDICATOR = {
    'id': 'EF-gf-3',
    'title': 'Test statistical table',
    'url': 'https://statbank.armstat.am/table.px/',
    'topic': 'Economy',
    'subtopics': ['Finance'],
}
JSON_STAT = {
    'version': '2.0',
    'class': 'dataset',
    'label': 'Test statistical table',
    'updated': '2024-01-01T00:00:00Z',
    'id': ['ContentsCode', 'years'],
    'size': [1, 2],
    'dimension': {
        'ContentsCode': {
            'label': 'EliminatedContents',
            'category': {
                'index': {'value': 0},
                'label': {'value': 'Test measure'},
                'unit': {'value': {'base': '%', 'decimals': 1}},
            },
        },
        'years': {
            'label': 'years',
            'category': {
                'index': {'2023': 0, '2024': 1},
                'label': {'2023': '2023', '2024': '2024'},
            },
        },
    },
    'role': {'metric': ['ContentsCode'], 'time': ['years']},
    'extension': {'px': {'matrix': 'EF-gf-3', 'subject-area': 'Economy'}},
    'value': [1, 2],
}
CSV_CONTENT = (
    b'"Test statistical table"\r\n\r\n'
    b'"years","2023","2024"\r\n'
    b'"Test measure",1,2\r\n'
)
RESOURCE_CONTENT = {
    'csv': CSV_CONTENT,
    'excel': b'xlsx content',
    'json-stat2': json.dumps(JSON_STAT).encode('utf-8'),
}


def cache_resources(data_dir, indicator):
    data_dir.mkdir(parents=True, exist_ok=True)
    for resource_type in RESOURCE_TYPES:
        path = data_dir / resource_name(indicator, resource_type['extension'])
        path.write_bytes(RESOURCE_CONTENT[resource_type['source_format']])


def remote_resources(indicator, data_dir):
    resources = []
    for resource_type in RESOURCE_TYPES:
        name = resource_name(indicator, resource_type['extension'])
        content = (data_dir / name).read_bytes()
        resources.append({
            'id': resource_type['key'] + '-id',
            'name': name,
            'hash': hashlib.sha256(content).hexdigest(),
            'url': 'https://example.test/' + name,
        })
    return resources


def synchronize_metadata(package, indicator, data_dir):
    metadata = package_metadata(
        indicator,
        dataset=JSON_STAT,
        csv_path=data_dir / resource_name(indicator),
    )
    package['notes'] = metadata['notes']
    package['extras'] = metadata['extras']
    return package


def make_response(payload, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = payload
    return response


def existing_package(indicator, resources=None):
    return {
        'id': 'package-id',
        'name': dataset_name(indicator),
        'url': indicator['url'],
        'owner_org': 'organization-id',
        'organization': {
            'id': 'organization-id',
            'name': 'opendataam',
        },
        'private': False,
        'resources': resources or [],
    }


class TestCKANClient(unittest.TestCase):
    @patch('statbank_parser.ckan.requests.Session.post')
    def test_http_error_contains_action_and_status(self, mock_post):
        mock_post.return_value = make_response({
            'success': False,
            'error': {'message': 'Not authorized'},
        }, 403)
        client = CKANClient('secret-token')

        with self.assertRaisesRegex(CKANError, 'package_create.*HTTP 403') as raised:
            client.package_create({'name': 'test'})

        self.assertNotIn('secret-token', str(raised.exception))

    @patch('statbank_parser.ckan.requests.Session.get')
    def test_package_show_returns_none_for_not_found(self, mock_get):
        mock_get.return_value = make_response({
            'success': False,
            'error': {'message': 'Not found'},
        }, 404)
        client = CKANClient('secret-token')

        self.assertIsNone(client.package_show('missing'))
        self.assertEqual(mock_get.call_args.kwargs['params'], {'id': 'missing'})

    def test_only_read_requests_are_automatically_retried(self):
        client = CKANClient('secret-token')
        retries = client.session.get_adapter('https://').max_retries

        self.assertEqual(retries.allowed_methods, frozenset(('GET',)))

    @patch('statbank_parser.ckan.requests.Session.post')
    def test_resource_create_uses_multipart_upload(self, mock_post):
        uploaded = {}

        def capture_upload(url, **kwargs):
            uploaded['content'] = kwargs['files']['upload'][1].read()
            return make_response({
                'success': True,
                'result': {'id': 'resource-id', 'url': 'https://example.test/data.csv'},
            })

        mock_post.side_effect = capture_upload
        client = CKANClient('secret-token')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'table.csv'
            path.write_bytes(b'a,b\n1,2\n')
            result = client.resource_upload(
                'package-id',
                path,
                'table.csv',
                'Test CSV',
                'test-hash',
            )

        self.assertEqual(result['id'], 'resource-id')
        self.assertEqual(uploaded['content'], b'a,b\n1,2\n')
        self.assertTrue(mock_post.call_args.args[0].endswith('/resource_create'))
        data = mock_post.call_args.kwargs['data']
        self.assertEqual(data['package_id'], 'package-id')
        self.assertEqual(data['hash'], 'test-hash')
        self.assertEqual(data['format'], 'CSV')
        self.assertIsNone(mock_post.call_args.kwargs['json'])

    def test_preflight_rejects_organization_without_permission(self):
        client = CKANClient('secret-token')
        client._action = Mock(return_value=[{'name': 'another-organization'}])

        with self.assertRaisesRegex(CKANError, 'does not grant'):
            client.ensure_can_create_datasets()


class TestPublicationMetadata(unittest.TestCase):
    def test_names_are_stable_and_duplicate_ids_do_not_collide(self):
        other = dict(INDICATOR, url='https://statbank.armstat.am/other.px/')

        first_name = dataset_name(INDICATOR)
        second_name = dataset_name(other)

        self.assertEqual(first_name, dataset_name(dict(INDICATOR)))
        self.assertNotEqual(first_name, second_name)
        self.assertLessEqual(len(first_name), 100)
        self.assertRegex(first_name, re.compile(r'^[a-z0-9_-]+$'))

    def test_package_metadata_is_public_and_preserves_source(self):
        metadata = package_metadata(INDICATOR)

        self.assertFalse(metadata['private'])
        self.assertEqual(metadata['owner_org'], 'opendataam')
        self.assertEqual(metadata['groups'], [{'name': 'statistics'}])
        self.assertEqual(metadata['license_id'], 'other-pd')
        self.assertEqual(metadata['url'], INDICATOR['url'])
        self.assertIn('Finance', metadata['notes'])
        self.assertIn(
            {'key': 'statbank_table_id', 'value': INDICATOR['id']},
            metadata['extras'],
        )

    def test_rich_metadata_describes_dimensions_units_and_csv_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / 'table.csv'
            csv_path.write_bytes(CSV_CONTENT)
            metadata = package_metadata(
                INDICATOR,
                dataset=JSON_STAT,
                csv_path=csv_path,
            )

        notes = metadata['notes']
        self.assertIn('## Contents', notes)
        self.assertIn('## Data structure', notes)
        self.assertIn('period: 2023–2024', notes)
        self.assertIn('unit: %, 1 decimals', notes)
        self.assertIn('**1 data rows** and **3 columns**', notes)
        self.assertIn('JSON-stat 2', notes)
        extras = {item['key']: item['value'] for item in metadata['extras']}
        self.assertEqual(extras['source_updated'], '2024-01-01T00:00:00Z')
        self.assertEqual(extras['cell_count'], '2')
        self.assertEqual(extras['csv_rows'], '1')
        self.assertEqual(extras['csv_columns'], '3')
        self.assertIn('ContentsCode', extras['dimensions'])


class TestPublicationPipeline(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.directory.name) / 'exports'
        self.report_path = Path(self.directory.name) / 'report.jsonl'
        self.client = Mock()
        self.client.base_url = 'https://data.opendata.am'
        self.client.resource_upload.side_effect = self.upload
        self.scraper = Mock()
        self.scraper.get_table_data.side_effect = (
            lambda url, file_format: RESOURCE_CONTENT[file_format]
        )

    def tearDown(self):
        self.directory.cleanup()

    @staticmethod
    def upload(**kwargs):
        name = kwargs['resource_name']
        return {
            'id': kwargs.get('resource_id') or name + '-id',
            'url': 'https://example.test/' + name,
        }

    def publish(self, indicators=None):
        return publish_indicators(
            indicators or [INDICATOR],
            self.client,
            data_dir=self.data_dir,
            report_path=self.report_path,
            scraper=self.scraper,
            delay=0,
        )

    def test_create_downloads_and_uploads_all_formats(self):
        self.client.package_show.return_value = None
        self.client.package_create.return_value = existing_package(INDICATOR)

        results = self.publish()

        self.assertEqual(results[0]['status'], 'created')
        self.assertEqual(len(results[0]['resources']), 3)
        self.assertEqual(self.client.resource_upload.call_count, 3)
        self.assertEqual(
            [call.kwargs['file_format'] for call in self.scraper.get_table_data.call_args_list],
            ['csv', 'excel', 'json-stat2'],
        )
        metadata = self.client.package_create.call_args.args[0]
        self.assertIn('## Data structure', metadata['notes'])
        self.assertIn('period: 2023–2024', metadata['notes'])
        report = json.loads(self.report_path.read_text().strip())
        self.assertEqual(len(report['resources']), 3)
        self.assertEqual(report['sha256'], hashlib.sha256(CSV_CONTENT).hexdigest())

    def test_existing_csv_card_gains_xlsx_and_json_without_replacing_csv(self):
        cache_resources(self.data_dir, INDICATOR)
        resources = remote_resources(INDICATOR, self.data_dir)
        package = synchronize_metadata(
            existing_package(INDICATOR, resources[:1]),
            INDICATOR,
            self.data_dir,
        )
        self.client.package_show.return_value = package

        results = self.publish()

        self.assertEqual(results[0]['status'], 'updated')
        self.assertEqual(results[0]['resource_id'], 'csv-id')
        self.assertEqual(self.client.resource_upload.call_count, 2)
        self.assertEqual(
            [call.kwargs['resource_format'] for call in self.client.resource_upload.call_args_list],
            ['XLSX', 'JSON-stat 2'],
        )
        self.assertEqual(results[0]['resources'][0]['status'], 'unchanged')
        self.client.package_patch.assert_not_called()

    def test_unchanged_card_is_not_downloaded_patched_or_uploaded_again(self):
        cache_resources(self.data_dir, INDICATOR)
        package = synchronize_metadata(
            existing_package(INDICATOR, remote_resources(INDICATOR, self.data_dir)),
            INDICATOR,
            self.data_dir,
        )
        self.client.package_show.return_value = package

        results = self.publish()

        self.assertEqual(results[0]['status'], 'unchanged')
        self.client.package_create.assert_not_called()
        self.client.package_patch.assert_not_called()
        self.client.resource_upload.assert_not_called()
        self.scraper.get_table_data.assert_not_called()

    def test_changed_resource_is_updated_without_duplicate(self):
        cache_resources(self.data_dir, INDICATOR)
        resources = remote_resources(INDICATOR, self.data_dir)
        resources[1]['hash'] = 'old-hash'
        package = synchronize_metadata(
            existing_package(INDICATOR, resources),
            INDICATOR,
            self.data_dir,
        )
        self.client.package_show.return_value = package

        results = self.publish()

        self.assertEqual(results[0]['status'], 'updated')
        self.client.resource_upload.assert_called_once()
        self.assertEqual(self.client.resource_upload.call_args.kwargs['resource_id'], 'xlsx-id')
        self.assertEqual(results[0]['resources'][1]['status'], 'updated')
        self.client.package_create.assert_not_called()
        self.client.package_patch.assert_not_called()

    def test_metadata_patch_preserves_package_and_resource_ids(self):
        cache_resources(self.data_dir, INDICATOR)
        package = existing_package(INDICATOR, remote_resources(INDICATOR, self.data_dir))
        package['notes'] = 'Short description'
        package['extras'] = []
        self.client.package_show.return_value = package
        self.client.package_patch.side_effect = lambda package_id, metadata: synchronize_metadata(
            package,
            INDICATOR,
            self.data_dir,
        )

        results = self.publish()

        self.assertEqual(results[0]['status'], 'updated')
        self.assertTrue(results[0]['metadata_updated'])
        self.assertEqual(self.client.package_patch.call_args.args[0], 'package-id')
        self.client.resource_upload.assert_not_called()
        self.assertEqual(results[0]['resource_id'], 'csv-id')

    def test_single_failure_is_reported_and_next_table_is_processed(self):
        other = dict(INDICATOR, id='other', url='https://statbank.armstat.am/other.px/')
        self.client.package_show.side_effect = [CKANError('temporary failure'), None]
        self.client.package_create.return_value = existing_package(other)

        results = self.publish([INDICATOR, other])

        self.assertEqual([result['status'] for result in results], ['error', 'created'])
        report_lines = self.report_path.read_text().splitlines()
        self.assertEqual(len(report_lines), 2)
        self.assertEqual(json.loads(report_lines[0])['error'], 'temporary failure')

    def test_existing_dataset_with_different_source_is_not_modified(self):
        package = existing_package(INDICATOR)
        package['url'] = 'https://example.test/different-source'
        self.client.package_show.return_value = package

        results = self.publish()

        self.assertEqual(results[0]['status'], 'error')
        self.client.package_create.assert_not_called()
        self.client.package_patch.assert_not_called()
        self.client.resource_upload.assert_not_called()
        self.scraper.get_table_data.assert_not_called()


class TestPublishCLI(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def write_catalog(self, filename='catalog.jsonl'):
        Path(filename).write_text(
            json.dumps(INDICATOR) + '\n',
            encoding='utf-8',
        )

    @patch('statbank_parser.cli.CKANClient')
    def test_dry_run_does_not_require_token_or_create_client(self, mock_client):
        with self.runner.isolated_filesystem():
            self.write_catalog()
            with patch.dict(os.environ, {'CKAN_API_TOKEN': ''}):
                result = self.runner.invoke(cli, [
                    'publish',
                    '--indicators', 'catalog.jsonl',
                    '--dry-run',
                ])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Validated 1 tables; no data was uploaded', result.output)
        mock_client.assert_not_called()

    @patch('statbank_parser.cli.CKANClient')
    def test_real_run_requires_token(self, mock_client):
        with self.runner.isolated_filesystem():
            self.write_catalog()
            with patch.dict(os.environ, {'CKAN_API_TOKEN': ''}):
                result = self.runner.invoke(cli, [
                    'publish',
                    '--indicators', 'catalog.jsonl',
                ])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('CKAN_API_TOKEN environment variable is required', result.output)
        mock_client.assert_not_called()

    @patch('statbank_parser.cli.publish_indicators')
    @patch('statbank_parser.cli.CKANClient')
    def test_partial_failure_returns_nonzero(self, mock_client_class, mock_publish):
        mock_publish.return_value = [
            {'status': 'created'},
            {'status': 'unchanged'},
            {'status': 'error'},
        ]
        with self.runner.isolated_filesystem():
            self.write_catalog()
            with patch.dict(os.environ, {'CKAN_API_TOKEN': 'secret-token'}):
                result = self.runner.invoke(cli, [
                    'publish',
                    '--indicators', 'catalog.jsonl',
                ])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('1 created/updated, 1 unchanged, 1 failed', result.output)
        mock_client_class.return_value.ensure_can_create_datasets.assert_called_once()


if __name__ == '__main__':
    unittest.main()
