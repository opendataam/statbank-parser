import unittest
from unittest.mock import Mock, patch, MagicMock
from bs4 import BeautifulSoup
import pandas as pd
from statbank_parser.scraper import StatbankScraper


class TestStatbankScraper(unittest.TestCase):
    """Test cases for StatbankScraper class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.scraper = StatbankScraper()
        self.test_url = "https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__1%20Econnomy%20and%20finance__15%20National%20Accounts/EF-NA-01.px/"
    
    def test_init(self):
        """Test scraper initialization"""
        self.assertIsNotNone(self.scraper.session)
        self.assertEqual(self.scraper.BASE_URL, "https://statbank.armstat.am/pxweb/en/ArmStatBank/")
    
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_traverse_category_with_tables(self, mock_get):
        """Test _traverse_category finds tables correctly"""
        # Mock HTML with table links
        html = """
        <html>
            <body>
                <div id="pxwebcontent">
                    <a href="table1.px/">Test Table 1</a>
                    <a href="table2.px">Test Table 2</a>
                </div>
            </body>
        </html>
        """
        mock_response = Mock()
        mock_response.content = html.encode('utf-8')
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        # Initialize visited set
        self.scraper.visited = set()
        
        result = self.scraper._traverse_category("http://test.com", ["Topic1"])
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['title'], 'Test Table 1')
        self.assertEqual(result[0]['topic'], 'Topic1')
        self.assertIn('.px', result[0]['url'])
    
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_traverse_category_with_postback(self, mock_get):
        """Test _traverse_category handles PostBack links"""
        html = """
        <html>
            <body>
                <div id="pxwebcontent">
                    <a href="javascript:__doPostBack('MenuNavigationTree','pArmStatBank__1 Test')">Category 1</a>
                </div>
            </body>
        </html>
        """
        mock_response = Mock()
        mock_response.content = html.encode('utf-8')
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        # Initialize visited set
        self.scraper.visited = set()
        
        # Should handle PostBack without errors
        result = self.scraper._traverse_category("http://test.com", [])
        self.assertIsInstance(result, list)
    
    @patch('statbank_parser.scraper.requests.Session.post')
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_get_available_formats(self, mock_get, mock_post):
        """Test get_available_formats retrieves format list"""
        # Mock initial page
        initial_html = """
        <html>
            <form id="aspnetForm">
                <input id="__VIEWSTATE" value="test_viewstate"/>
                <input id="__EVENTVALIDATION" value="test_validation"/>
                <select name="var1"><option value="2024">2024</option></select>
                <input type="submit" name="btn" value="Show table"/>
            </form>
        </html>
        """
        
        # Mock result page with formats
        result_html = """
        <html>
            <body>
                <label for="ctl00_SaveAsRadioButtonList_0">Excel workbook (xml)</label>
                <label for="ctl00_SaveAsRadioButtonList_1">CSV file</label>
                <label for="ctl00_SaveAsRadioButtonList_2">JSON-stat file (json)</label>
            </body>
        </html>
        """
        
        mock_get_response = Mock()
        mock_get_response.content = initial_html.encode('utf-8')
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response
        
        mock_post_response = Mock()
        mock_post_response.content = result_html.encode('utf-8')
        mock_post_response.raise_for_status = Mock()
        mock_post.return_value = mock_post_response
        
        formats = self.scraper.get_available_formats(self.test_url)
        
        self.assertEqual(len(formats), 3)
        self.assertIn('Excel workbook (xml)', formats)
        self.assertIn('CSV file', formats)
        self.assertIn('JSON-stat file (json)', formats)
    
    @patch('statbank_parser.scraper.pd.read_html')
    @patch('statbank_parser.scraper.requests.Session.post')
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_get_table_data_default(self, mock_get, mock_post, mock_read_html):
        """Test get_table_data with default HTML parsing"""
        # Mock initial page
        initial_html = """
        <html>
            <form id="aspnetForm">
                <input id="__VIEWSTATE" value="test_viewstate"/>
                <input id="__EVENTVALIDATION" value="test_validation"/>
                <select name="var1"><option value="2024">2024</option></select>
                <input type="submit" name="btn" value="Show table"/>
            </form>
        </html>
        """
        
        # Mock result page with table
        result_html = """
        <html>
            <body>
                <table class="pxweb-table">
                    <tr><th>Year</th><th>Value</th></tr>
                    <tr><td>2024</td><td>100</td></tr>
                </table>
            </body>
        </html>
        """
        
        mock_get_response = Mock()
        mock_get_response.content = initial_html.encode('utf-8')
        mock_get_response.raise_for_status = Mock()
        mock_get.return_value = mock_get_response
        
        mock_post_response = Mock()
        mock_post_response.content = result_html.encode('utf-8')
        mock_post_response.raise_for_status = Mock()
        mock_post.return_value = mock_post_response
        
        # Mock pandas read_html
        mock_df = pd.DataFrame({'Year': [2024], 'Value': [100]})
        mock_read_html.return_value = [mock_df]
        
        result = self.scraper.get_table_data(self.test_url)
        
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(len(result), 1)
        self.assertIn('Year', result.columns)
    
    def test_get_indicators_initializes_visited(self):
        """Test get_indicators initializes visited set"""
        with patch.object(self.scraper, '_traverse_category', return_value=[]):
            self.scraper.get_indicators()
            self.assertIsInstance(self.scraper.visited, set)
    
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_traverse_category_prevents_infinite_loops(self, mock_get):
        """Test that visited URLs are not traversed again"""
        html = """
        <html>
            <body>
                <div id="pxwebcontent">
                    <a href="test.px/">Test</a>
                </div>
            </body>
        </html>
        """
        mock_response = Mock()
        mock_response.content = html.encode('utf-8')
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response
        
        url = "http://test.com"
        self.scraper.visited = set()
        
        # First call should process
        result1 = self.scraper._traverse_category(url, [])
        self.assertEqual(len(result1), 1)
        
        # Second call should return empty (already visited)
        result2 = self.scraper._traverse_category(url, [])
        self.assertEqual(len(result2), 0)


class TestTableIDExtraction(unittest.TestCase):
    """Test table ID extraction logic"""
    
    def test_extract_id_from_url_with_trailing_slash(self):
        """Test ID extraction from URL with trailing slash"""
        from urllib.parse import urlparse
        url = "https://example.com/path/EF-NA-01.px/"
        path = urlparse(url).path
        filename = path.split('/')[-1]
        if not filename:
            filename = path.split('/')[-2]
        table_id = filename.replace('.px', '')
        self.assertEqual(table_id, 'EF-NA-01')
    
    def test_extract_id_from_url_without_trailing_slash(self):
        """Test ID extraction from URL without trailing slash"""
        from urllib.parse import urlparse
        url = "https://example.com/path/EF-NA-01.px"
        path = urlparse(url).path
        filename = path.split('/')[-1]
        if not filename:
            filename = path.split('/')[-2]
        table_id = filename.replace('.px', '')
        self.assertEqual(table_id, 'EF-NA-01')


if __name__ == '__main__':
    unittest.main()
