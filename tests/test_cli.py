import json
import os
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from click.testing import CliRunner

from statbank_parser.cli import cli


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    @patch('statbank_parser.cli.StatbankScraper')
    def test_list_indicators_command(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_indicators.return_value = [
            {
                'id': 'EF-NA-01',
                'title': 'Test Indicator 1',
                'url': 'http://test.com/table1.px/',
                'topic': 'Economy',
                'subtopics': ['National Accounts'],
            },
            {
                'id': 'EF-NA-02',
                'title': 'Test Indicator 2',
                'url': 'http://test.com/table2.px/',
                'topic': 'Economy',
                'subtopics': [],
            },
        ]
        mock_scraper_class.return_value = mock_scraper

        result = self.runner.invoke(cli, ['list-indicators'])

        self.assertEqual(result.exit_code, 0)
        lines = result.output.strip().split('\n')
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])['id'], 'EF-NA-01')
        self.assertEqual(json.loads(lines[1])['id'], 'EF-NA-02')

    @patch('statbank_parser.cli.StatbankScraper')
    def test_list_indicators_command_error_handling(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_indicators.side_effect = Exception('Network error')
        mock_scraper_class.return_value = mock_scraper

        result = self.runner.invoke(cli, ['list-indicators'])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Error: Network error', result.output)

    @patch('statbank_parser.cli.StatbankScraper')
    def test_list_formats_command(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_available_formats.return_value = [
            'Excel workbook (xml)',
            'Comma delimited with heading',
            'JSON-stat file (json)',
        ]
        mock_scraper_class.return_value = mock_scraper

        result = self.runner.invoke(cli, [
            'list-formats',
            '--url', 'http://test.com/table.px/',
        ])

        self.assertEqual(result.exit_code, 0)
        self.assertIn('Available formats:', result.output)
        self.assertIn('Excel workbook (xml)', result.output)
        self.assertIn('Comma delimited with heading', result.output)
        self.assertIn('JSON-stat file (json)', result.output)

    @patch('statbank_parser.cli.StatbankScraper')
    def test_list_formats_command_error_handling(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_available_formats.side_effect = Exception('Network error')
        mock_scraper_class.return_value = mock_scraper

        result = self.runner.invoke(cli, [
            'list-formats',
            '--url', 'http://test.com/table.px/',
        ])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Error: Network error', result.output)

    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_default_csv(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_table_data.return_value = pd.DataFrame({
            'Year': [2024],
            'Value': [100],
        })
        mock_scraper_class.return_value = mock_scraper

        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, [
                'get-data',
                '--url', 'http://test.com/table.px/',
                '--output', 'test.csv',
            ])

            self.assertEqual(result.exit_code, 0)
            self.assertIn('Data saved to test.csv', result.output)
            self.assertTrue(os.path.exists('test.csv'))

    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_json_output(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_table_data.return_value = pd.DataFrame({
            'Year': [2024],
            'Value': [100],
        })
        mock_scraper_class.return_value = mock_scraper

        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, [
                'get-data',
                '--url', 'http://test.com/table.px/',
                '--output', 'test.json',
            ])

            self.assertEqual(result.exit_code, 0)
            self.assertIn('Data saved to test.json', result.output)
            self.assertTrue(os.path.exists('test.json'))

    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_with_format(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_table_data.return_value = b'binary file content'
        mock_scraper_class.return_value = mock_scraper

        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, [
                'get-data',
                '--url', 'http://test.com/table.px/',
                '--output', 'test.xlsx',
                '--format', 'excel',
            ])

            self.assertEqual(result.exit_code, 0)
            self.assertIn('Data saved to test.xlsx', result.output)
            self.assertTrue(os.path.exists('test.xlsx'))
            with open('test.xlsx', 'rb') as output_file:
                self.assertEqual(output_file.read(), b'binary file content')

    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_error_handling(self, mock_scraper_class):
        mock_scraper = Mock()
        mock_scraper.get_table_data.side_effect = Exception('Failed to fetch data')
        mock_scraper_class.return_value = mock_scraper

        result = self.runner.invoke(cli, [
            'get-data',
            '--url', 'http://test.com/table.px/',
            '--output', 'test.csv',
        ])

        self.assertEqual(result.exit_code, 1)
        self.assertIn('Error: Failed to fetch data', result.output)

    def test_cli_group_exists(self):
        result = self.runner.invoke(cli, ['--help'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('list-indicators', result.output)
        self.assertIn('list-formats', result.output)
        self.assertIn('get-data', result.output)


if __name__ == '__main__':
    unittest.main()
