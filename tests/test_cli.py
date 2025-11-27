import unittest
from unittest.mock import Mock, patch, MagicMock
from click.testing import CliRunner
import json
import pandas as pd
from statbank_parser.cli import cli


class TestCLI(unittest.TestCase):
    """Test cases for CLI commands"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.runner = CliRunner()
    
    @patch('statbank_parser.cli.StatbankScraper')
    def test_list_indicators_command(self, mock_scraper_class):
        """Test list-indicators command outputs JSONL"""
        # Mock scraper instance
        mock_scraper = Mock()
        mock_scraper.get_indicators.return_value = [
            {
                'id': 'EF-NA-01',
                'title': 'Test Indicator 1',
                'url': 'http://test.com/table1.px/',
                'topic': 'Economy',
                'subtopics': ['National Accounts']
            },
            {
                'id': 'EF-NA-02',
                'title': 'Test Indicator 2',
                'url': 'http://test.com/table2.px/',
                'topic': 'Economy',
                'subtopics': []
            }
        ]
        mock_scraper_class.return_value = mock_scraper
        
        result = self.runner.invoke(cli, ['list-indicators'])
        
        self.assertEqual(result.exit_code, 0)
        
        # Verify JSONL format (one JSON object per line)
        lines = result.output.strip().split('\n')
        self.assertEqual(len(lines), 2)
        
        # Verify each line is valid JSON
        obj1 = json.loads(lines[0])
        obj2 = json.loads(lines[1])
        
        self.assertEqual(obj1['id'], 'EF-NA-01')
        self.assertEqual(obj1['topic'], 'Economy')
        self.assertEqual(obj2['id'], 'EF-NA-02')
    
    @patch('statbank_parser.cli.StatbankScraper')
    def test_list_formats_command(self, mock_scraper_class):
        """Test list-formats command"""
        mock_scraper = Mock()
        mock_scraper.get_available_formats.return_value = [
            'Excel workbook (xml)',
            'CSV file',
            'JSON-stat file (json)'
        ]
        mock_scraper_class.return_value = mock_scraper
        
        result = self.runner.invoke(cli, [
            'list-formats',
            '--url', 'http://test.com/table.px/'
        ])
        
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Available formats:', result.output)
        self.assertIn('Excel workbook (xml)', result.output)
        self.assertIn('CSV file', result.output)
        self.assertIn('JSON-stat file (json)', result.output)
    
    @patch('statbank_parser.cli.StatbankScraper')
    def test_list_formats_command_error_handling(self, mock_scraper_class):
        """Test list-formats command handles errors"""
        mock_scraper = Mock()
        mock_scraper.get_available_formats.side_effect = Exception("Network error")
        mock_scraper_class.return_value = mock_scraper
        
        result = self.runner.invoke(cli, [
            'list-formats',
            '--url', 'http://test.com/table.px/'
        ])
        
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Error:', result.output)
    
    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_default_csv(self, mock_scraper_class):
        """Test get-data command with default CSV output"""
        mock_scraper = Mock()
        mock_df = pd.DataFrame({'Year': [2024], 'Value': [100]})
        mock_scraper.get_table_data.return_value = mock_df
        mock_scraper_class.return_value = mock_scraper
        
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, [
                'get-data',
                '--url', 'http://test.com/table.px/',
                '--output', 'test.csv'
            ])
            
            self.assertEqual(result.exit_code, 0)
            self.assertIn('Data saved to test.csv', result.output)
            
            # Verify file was created
            import os
            self.assertTrue(os.path.exists('test.csv'))
    
    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_json_output(self, mock_scraper_class):
        """Test get-data command with JSON output"""
        mock_scraper = Mock()
        mock_df = pd.DataFrame({'Year': [2024], 'Value': [100]})
        mock_scraper.get_table_data.return_value = mock_df
        mock_scraper_class.return_value = mock_scraper
        
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, [
                'get-data',
                '--url', 'http://test.com/table.px/',
                '--output', 'test.json'
            ])
            
            self.assertEqual(result.exit_code, 0)
            self.assertIn('Data saved to test.json', result.output)
            
            # Verify file was created
            import os
            self.assertTrue(os.path.exists('test.json'))
    
    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_with_format(self, mock_scraper_class):
        """Test get-data command with format option"""
        mock_scraper = Mock()
        mock_scraper.get_table_data.return_value = b'binary file content'
        mock_scraper_class.return_value = mock_scraper
        
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(cli, [
                'get-data',
                '--url', 'http://test.com/table.px/',
                '--output', 'test.xlsx',
                '--format', 'excel'
            ])
            
            self.assertEqual(result.exit_code, 0)
            self.assertIn('Data saved to test.xlsx', result.output)
            
            # Verify file was created with binary content
            import os
            self.assertTrue(os.path.exists('test.xlsx'))
            with open('test.xlsx', 'rb') as f:
                content = f.read()
                self.assertEqual(content, b'binary file content')
    
    @patch('statbank_parser.cli.StatbankScraper')
    def test_get_data_command_error_handling(self, mock_scraper_class):
        """Test get-data command handles errors"""
        mock_scraper = Mock()
        mock_scraper.get_table_data.side_effect = Exception("Failed to fetch data")
        mock_scraper_class.return_value = mock_scraper
        
        result = self.runner.invoke(cli, [
            'get-data',
            '--url', 'http://test.com/table.px/',
            '--output', 'test.csv'
        ])
        
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Error:', result.output)
        self.assertIn('Failed to fetch data', result.output)
    
    def test_cli_group_exists(self):
        """Test CLI group is properly defined"""
        result = self.runner.invoke(cli, ['--help'])
        self.assertEqual(result.exit_code, 0)
        self.assertIn('list-indicators', result.output)
        self.assertIn('list-formats', result.output)
        self.assertIn('get-data', result.output)


if __name__ == '__main__':
    unittest.main()
