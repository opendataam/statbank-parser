import json
import unittest
from io import BytesIO
from itertools import product
from unittest.mock import Mock, patch
from urllib.parse import quote

import pandas as pd
import requests
from bs4 import BeautifulSoup
from openpyxl import Workbook, load_workbook

from statbank_parser.scraper import StatbankScraper


INITIAL_HTML = """
<html>
    <form id="aspnetForm">
        <input id="__VIEWSTATE" value="test_viewstate"/>
        <input id="__EVENTVALIDATION" value="test_validation"/>
        <select name="var1"><option value="2024">2024</option></select>
        <input type="submit" name="btn" value="Show table"/>
    </form>
</html>
"""

RESULT_HTML = """
<html>
    <body>
        <input type="radio" id="ctl00_SaveAsRadioButtonList_0" value="/download/excel-xml"/>
        <label for="ctl00_SaveAsRadioButtonList_0">Excel workbook (xml)</label>
        <input type="radio" id="ctl00_SaveAsRadioButtonList_1" value="/download/csv"/>
        <label for="ctl00_SaveAsRadioButtonList_1">Comma delimited with heading</label>
        <input type="radio" id="ctl00_SaveAsRadioButtonList_2" value="/download/json-stat"/>
        <label for="ctl00_SaveAsRadioButtonList_2">JSON-stat file (json)</label>
        <input type="radio" id="ctl00_SaveAsRadioButtonList_3" value="/download/excel"/>
        <label for="ctl00_SaveAsRadioButtonList_3">Excel (xlsx)</label>
    </body>
</html>
"""


def make_response(content, url):
    response = Mock()
    response.content = content.encode('utf-8') if isinstance(content, str) else content
    response.url = url
    response.raise_for_status = Mock()
    return response


JSON_STAT2_DIMENSIONS = (
    ('regions', ['Total', 'North', 'South']),
    ('indicators', ['Output', 'Index']),
    # Statbank tables can repeat a category label for different codes.
    ('years', ['2006', '2025', '2007', '2008', '2025']),
)


def json_stat2_table(selection=None, sparse=False):
    """Build a JSON-stat 2 table whose values identify their cell."""
    selection = selection or {}
    ids = [dimension_id for dimension_id, _ in JSON_STAT2_DIMENSIONS]
    codes = {
        dimension_id: selection.get(
            dimension_id,
            [str(index) for index in range(len(labels))],
        )
        for dimension_id, labels in JSON_STAT2_DIMENSIONS
    }
    dimension = {
        dimension_id: {
            'label': dimension_id,
            'category': {
                'index': {code: index for index, code in enumerate(codes[dimension_id])},
                'label': {code: labels[int(code)] for code in codes[dimension_id]},
            },
        }
        for dimension_id, labels in JSON_STAT2_DIMENSIONS
    }
    values = []
    status = {}
    for index, cell in enumerate(product(*(codes[dimension_id] for dimension_id in ids))):
        region, indicator, year = (int(code) for code in cell)
        if (region + indicator + year) % 3 == 0:
            values.append(None)
            status[str(index)] = '..'
        else:
            values.append(region * 100 + indicator * 10 + year + 0.5)
    return {
        'version': '2.0',
        'class': 'dataset',
        'label': 'Large table',
        'updated': '2026-01-01T00:00:00Z',
        'id': ids,
        'size': [len(codes[dimension_id]) for dimension_id in ids],
        'dimension': dimension,
        'value': (
            {str(index): value for index, value in enumerate(values) if value is not None}
            if sparse
            else values
        ),
        'status': status,
    }


class TestStatbankScraper(unittest.TestCase):
    def setUp(self):
        self.scraper = StatbankScraper()
        self.test_url = 'https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__1%20Topic/EF-NA-01.px/'
        self.result_url = 'https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__1%20Topic/EF-NA-01.px/table/tableViewLayout1/'
        self.initial_response = make_response(INITIAL_HTML, self.test_url)
        self.result_response = make_response(RESULT_HTML, self.result_url)
        self.result_soup = BeautifulSoup(RESULT_HTML, 'html.parser')

    def test_init(self):
        self.assertIsNotNone(self.scraper.session)
        self.assertEqual(self.scraper.timeout, (10, 60))
        retries = self.scraper.session.get_adapter('https://').max_retries
        self.assertEqual(retries.total, 3)
        self.assertIn(429, retries.status_forcelist)

    @patch('statbank_parser.scraper.requests.Session.get')
    def test_traverse_category_with_tables(self, mock_get):
        html = """
        <html><body><div id="pxwebcontent">
            <a href="table1.px/">Test Table 1</a>
            <a href="table2.px">Test Table 2</a>
        </div></body></html>
        """
        mock_get.return_value = make_response(html, 'http://test.com')
        self.scraper.visited = set()

        result = self.scraper._traverse_category('http://test.com', ['Topic1'])

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['id'], 'table1')
        self.assertEqual(result[1]['id'], 'table2')
        self.assertEqual(result[0]['topic'], 'Topic1')
        mock_get.assert_called_once_with(
            'http://test.com',
            timeout=self.scraper.timeout,
        )

    @patch('statbank_parser.scraper.requests.Session.get')
    def test_traverse_category_uses_only_direct_children(self, mock_get):
        root_html = """
        <div id="pxwebcontent">
            <a href="javascript:__doPostBack('MenuNavigationTree','pArmStatBank__1 Topic')">Category 1</a>
        </div>
        """
        topic_html = """
        <div id="pxwebcontent">
            <a href="javascript:__doPostBack('MenuNavigationTree','pArmStatBank__2 Other')">Other topic</a>
            <a href="javascript:__doPostBack('MenuNavigationTree','pArmStatBank__1 Topic__2 Child')">Child Category</a>
            <a href="https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__2 Other/Wrong.px/">Wrong table</a>
        </div>
        """
        child_html = """
        <div id="pxwebcontent">
            <a href="https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__1 Topic__2 Child/Table.px/">Correct table</a>
            <a href="https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__2 Other/Wrong.px/">Wrong table</a>
        </div>
        """
        topic_node = 'ArmStatBank__1 Topic'
        child_node = 'ArmStatBank__1 Topic__2 Child'
        responses = {
            self.scraper.BASE_URL: make_response(root_html, self.scraper.BASE_URL),
            self.scraper.BASE_URL + quote(topic_node): make_response(
                topic_html,
                self.scraper.BASE_URL + quote(topic_node),
            ),
            self.scraper.BASE_URL + quote(child_node): make_response(
                child_html,
                self.scraper.BASE_URL + quote(child_node),
            ),
        }
        mock_get.side_effect = lambda url, timeout: responses[url]
        self.scraper.visited = set()

        result = self.scraper._traverse_category(self.scraper.BASE_URL, [])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['id'], 'Table')
        self.assertEqual(result[0]['topic'], 'Category 1')
        self.assertEqual(result[0]['subtopics'], ['Child Category'])
        self.assertEqual(mock_get.call_count, 3)

    @patch('statbank_parser.scraper.requests.Session.post')
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_get_available_formats(self, mock_get, mock_post):
        mock_get.return_value = self.initial_response
        mock_post.return_value = self.result_response

        formats = self.scraper.get_available_formats(self.test_url)

        self.assertEqual(formats, [
            'Excel workbook (xml)',
            'Comma delimited with heading',
            'JSON-stat file (json)',
            'Excel (xlsx)',
        ])
        self.assertEqual(
            mock_post.call_args.kwargs['data']['var1'],
            ['2024'],
        )
        self.assertEqual(
            mock_post.call_args.kwargs['timeout'],
            self.scraper.timeout,
        )

    @patch('statbank_parser.scraper.requests.Session.post')
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_get_table_data_default_downloads_complete_csv(self, mock_get, mock_post):
        years = [str(year) for year in range(1993, 2027)]
        csv_text = '\ufeff"Table title"\r\n\r\n'
        csv_text += '"months",' + ','.join(f'"{year}"' for year in years) + '\r\n'
        csv_text += '"January",' + ','.join(['100'] * len(years)) + '\r\n'
        download_response = make_response(csv_text.encode('utf-8'), 'https://statbank.armstat.am/download/csv')
        mock_get.side_effect = [self.initial_response, download_response]
        mock_post.return_value = self.result_response

        result = self.scraper.get_table_data(self.test_url)

        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(result.shape, (1, 35))
        self.assertEqual(result.columns[0], 'months')
        self.assertEqual(result.columns[-1], '2026')
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(
            mock_get.call_args_list[1].args[0],
            'https://statbank.armstat.am/download/csv',
        )

    @patch('statbank_parser.scraper.requests.Session.post')
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_get_table_data_format_aliases_use_direct_download(self, mock_get, mock_post):
        cases = (
            ('csv', b'csv content', '/download/csv'),
            ('json-stat', b'{"dataset": {}}', '/download/json-stat'),
            ('excel', b'PK\x03\x04', '/download/excel'),
        )
        for file_format, content, path in cases:
            with self.subTest(file_format=file_format):
                mock_get.reset_mock()
                mock_post.reset_mock()
                mock_get.side_effect = [
                    self.initial_response,
                    make_response(content, 'https://statbank.armstat.am' + path),
                ]
                mock_post.return_value = self.result_response

                result = self.scraper.get_table_data(self.test_url, file_format)

                self.assertEqual(result, content)
                self.assertEqual(mock_post.call_count, 1)
                self.assertEqual(
                    mock_get.call_args_list[1].args[0],
                    'https://statbank.armstat.am' + path,
                )
                self.assertEqual(
                    mock_get.call_args_list[1].kwargs['timeout'],
                    self.scraper.timeout,
                )

    @patch('statbank_parser.scraper.requests.Session.post')
    @patch('statbank_parser.scraper.requests.Session.get')
    def test_get_table_data_rejects_unknown_format(self, mock_get, mock_post):
        mock_get.return_value = self.initial_response
        mock_post.return_value = self.result_response

        with self.assertRaisesRegex(ValueError, 'Available aliases'):
            self.scraper.get_table_data(self.test_url, 'unknown')

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(mock_post.call_count, 1)

    def test_get_indicators_initializes_visited_and_deduplicates_urls(self):
        item = {
            'id': 'EF-NA-01',
            'title': 'Test',
            'url': 'http://test.com/table.px/',
            'topic': 'Topic',
            'subtopics': [],
        }
        other = dict(item, id='EF-NA-02', url='http://test.com/other.px/')
        with patch.object(
            self.scraper,
            '_traverse_category',
            return_value=[item, dict(item), other],
        ):
            result = self.scraper.get_indicators()

        self.assertIsInstance(self.scraper.visited, set)
        self.assertEqual(result, [item, other])

    @patch('statbank_parser.scraper.requests.Session.get')
    def test_traverse_category_prevents_infinite_loops(self, mock_get):
        html = '<div id="pxwebcontent"><a href="test.px/">Test</a></div>'
        mock_get.return_value = make_response(html, 'http://test.com')
        self.scraper.visited = set()

        first = self.scraper._traverse_category('http://test.com', [])
        second = self.scraper._traverse_category('http://test.com', [])

        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(mock_get.call_count, 1)

    @patch('statbank_parser.scraper.requests.Session.get')
    def test_traverse_category_does_not_hide_network_errors(self, mock_get):
        mock_get.side_effect = requests.Timeout('request timed out')
        self.scraper.visited = set()

        with self.assertRaises(requests.Timeout):
            self.scraper._traverse_category('http://test.com', [])

    def test_get_table_data_uses_large_table_fallback(self):
        empty_result = BeautifulSoup('<html></html>', 'html.parser')
        with patch.object(
            self.scraper,
            '_get_table_result',
            return_value=(self.result_response, empty_result),
        ), patch.object(
            self.scraper,
            '_get_large_table_data',
            return_value=b'complete csv',
        ) as mock_large:
            result = self.scraper.get_table_data(self.test_url, 'csv')

        self.assertEqual(result, b'complete csv')
        mock_large.assert_called_once_with(self.test_url, 'csv')

    @patch('statbank_parser.scraper.requests.Session.post')
    def test_select_large_values_uses_advanced_search(self, mock_post):
        initial = BeautifulSoup("""
            <form id="aspnetForm">
                <input type="hidden" name="__VIEWSTATE" value="state"/>
                <a href="javascript:__doPostBack('SearchButton','')">Advanced search</a>
            </form>
        """, 'html.parser')
        advanced_html = """
            <form>
                <input name="SearchFetchAllButton" type="submit" value="Fetch all"/>
                <select name="SearchResults"></select>
                <select name="SelectedVariableValues"></select>
            </form>
        """
        mock_post.return_value = make_response(advanced_html, self.test_url)
        fetched = BeautifulSoup("""
            <form>
                <select name="SelectedVariableValues">
                    <option value="a" selected>A</option>
                    <option value="b" selected>B</option>
                </select>
            </form>
        """, 'html.parser')
        main = BeautifulSoup("""
            <form>
                <select name="values"><option value="a">A</option></select>
                <a href="javascript:__doPostBack('SearchButton','')">Advanced search</a>
            </form>
        """, 'html.parser')
        with patch.object(
            self.scraper,
            '_get_table_page',
            return_value=(self.initial_response, initial),
        ), patch.object(
            self.scraper,
            '_submit_form_button',
            side_effect=[
                (self.initial_response, fetched),
                (self.initial_response, main),
            ],
        ) as mock_submit:
            _, result = self.scraper._select_large_values(self.test_url)

        self.assertEqual(result, main)
        self.assertEqual(mock_post.call_args.kwargs['data']['__EVENTTARGET'], 'SearchButton')
        self.assertEqual(mock_submit.call_count, 2)
        self.assertEqual(mock_submit.call_args_list[0].args[2], 'FetchAllButton')
        self.assertEqual(mock_submit.call_args_list[1].args[2], 'DoneButton')
        self.assertEqual(
            mock_submit.call_args_list[1].args[3]['SelectedVariableValues'],
            ['a', 'b'],
        )

    def test_large_table_within_limit_selects_every_value(self):
        main = BeautifulSoup("""
            <form>
                <select name="categories"><option value="a"/><option value="b"/></select>
                <select name="years"><option value="2023"/><option value="2024"/></select>
            </form>
        """, 'html.parser')
        with patch.object(
            self.scraper,
            '_select_large_values',
            return_value=(self.initial_response, main),
        ), patch.object(
            self.scraper,
            '_submit_form_button',
            return_value=(self.result_response, self.result_soup),
        ) as mock_submit, patch.object(
            self.scraper,
            '_download_format',
            return_value=b'csv content',
        ):
            result = self.scraper._get_large_table_data(self.test_url, 'csv')

        self.assertEqual(result, b'csv content')
        selections = mock_submit.call_args.args[3]
        self.assertEqual(selections['categories'], ['a', 'b'])
        self.assertEqual(selections['years'], ['2023', '2024'])

    def test_large_table_chunks_and_merges_csv_without_losing_values(self):
        years = [str(year) for year in range(2000, 2020)]
        main = BeautifulSoup(
            '<form><select name="regions"><option value="A"/><option value="B"/></select>'
            '<select name="categories"><option value="x"/><option value="y"/><option value="z"/></select>'
            '<select name="years">'
            + ''.join(f'<option value="{year}"/>' for year in years)
            + '</select></form>',
            'html.parser',
        )

        def csv_chunk(chunk_years):
            lines = [
                '"Large table"',
                '',
                ','.join(['regions', 'categories'] + chunk_years),
                ','.join(['A', 'x'] + ['..'] * len(chunk_years)),
                ','.join(['B', 'y'] + ['1'] * len(chunk_years)),
            ]
            return ('\r\n'.join(lines) + '\r\n').encode('utf-8')

        with patch.object(
            self.scraper,
            '_select_large_values',
            return_value=(self.initial_response, main),
        ), patch.object(
            self.scraper,
            '_submit_form_button',
            return_value=(self.result_response, self.result_soup),
        ) as mock_submit, patch.object(
            self.scraper,
            '_download_format',
            side_effect=[csv_chunk(years[:10]), csv_chunk(years[10:])],
        ):
            result = self.scraper._get_large_table_data(
                self.test_url,
                'csv',
                max_cells=60,
            )

        self.assertEqual(mock_submit.call_count, 2)
        self.assertEqual(mock_submit.call_args_list[0].args[3]['years'], years[:10])
        self.assertEqual(mock_submit.call_args_list[1].args[3]['years'], years[10:])
        self.assertEqual(result.decode('utf-8-sig').splitlines()[:2], ['Large table', ''])
        frame = pd.read_csv(
            BytesIO(result),
            skiprows=2,
            dtype=str,
            keep_default_na=False,
        )
        self.assertEqual(frame.shape, (2, 22))
        self.assertEqual(frame.columns[0], 'regions')
        self.assertEqual(frame.columns[-1], '2019')
        self.assertEqual(frame.loc[0, '2000'], '..')
        self.assertEqual(frame.loc[1, '2019'], '1')

    def test_merge_json_stat2_chunks_preserves_values_and_sparse_status(self):
        def chunk(codes, values, status):
            return {
                'version': '2.0',
                'class': 'dataset',
                'label': 'Large table',
                'updated': '2026-01-01T00:00:00Z',
                'id': ['category', 'years'],
                'size': [1, len(codes)],
                'dimension': {
                    'category': {
                        'label': 'category',
                        'category': {'index': {'x': 0}, 'label': {'x': 'X'}},
                    },
                    'years': {
                        'label': 'years',
                        'category': {
                            'index': {code: index for index, code in enumerate(codes)},
                            'label': {code: code for code in codes},
                        },
                    },
                },
                'value': values,
                'status': status,
            }

        result = self.scraper._merge_json_stat2_chunks([
            json.dumps(chunk(['2023', '2024'], [10, 20], {'1': '..'})).encode(),
            json.dumps(chunk(['2025'], [30], {'0': '..'})).encode(),
        ])
        merged = json.loads(result)

        self.assertEqual(merged['size'], [1, 3])
        self.assertEqual(merged['value'], [10, 20, 30])
        self.assertEqual(merged['status'], {'1': '..', '2': '..'})
        category = merged['dimension']['years']['category']
        self.assertEqual(category['index'], {'2023': 0, '2024': 1, '2025': 2})
        self.assertEqual(category['label']['2025'], '2025')

    def test_large_table_chunks_and_merges_json_stat2_split_on_last_dimension(self):
        main = BeautifulSoup(
            '<form><select name="regions">'
            + ''.join(f'<option value="{code}"/>' for code in range(3))
            + '</select><select name="indicators">'
            + ''.join(f'<option value="{code}"/>' for code in range(2))
            + '</select><select name="years">'
            + ''.join(f'<option value="{code}"/>' for code in range(5))
            + '</select></form>',
            'html.parser',
        )
        chunks = [['0', '1'], ['2', '3'], ['4']]

        with patch.object(
            self.scraper,
            '_select_large_values',
            return_value=(self.initial_response, main),
        ), patch.object(
            self.scraper,
            '_submit_form_button',
            return_value=(self.result_response, self.result_soup),
        ) as mock_submit, patch.object(
            self.scraper,
            '_download_format',
            side_effect=[
                json.dumps(json_stat2_table({'years': chunk})).encode()
                for chunk in chunks
            ],
        ):
            result = self.scraper._get_large_table_data(
                self.test_url,
                'json-stat2',
                max_cells=15,
            )

        self.assertEqual(
            [call.args[3]['years'] for call in mock_submit.call_args_list],
            chunks,
        )
        self.assertEqual(json.loads(result), json_stat2_table())

    def test_merge_json_stat2_chunks_matches_unsplit_table_for_any_dimension(self):
        for dimension_id, labels in JSON_STAT2_DIMENSIONS:
            codes = [str(index) for index in range(len(labels))]
            for sparse in (False, True):
                with self.subTest(dimension=dimension_id, sparse=sparse):
                    chunks = [
                        json.dumps(json_stat2_table({dimension_id: part}, sparse)).encode()
                        for part in (codes[:1], codes[1:])
                    ]

                    merged = json.loads(self.scraper._merge_json_stat2_chunks(chunks))

                    self.assertEqual(merged, json_stat2_table(sparse=sparse))

    def test_merge_json_stat2_chunks_rejects_chunks_split_on_several_dimensions(self):
        chunks = [
            json.dumps(json_stat2_table({'regions': ['0'], 'years': ['0']})).encode(),
            json.dumps(json_stat2_table({'regions': ['1'], 'years': ['1']})).encode(),
        ]

        with self.assertRaisesRegex(ValueError, 'exactly one dimension'):
            self.scraper._merge_json_stat2_chunks(chunks)

    def test_merge_csv_chunks_keeps_value_labels_repeated_between_chunks(self):
        def csv_chunk(years, rows):
            lines = ['"Large table"', '', ','.join(['regions', 'indicators'] + years)]
            lines.extend(','.join(row) for row in rows)
            return ('\r\n'.join(lines) + '\r\n').encode('utf-8')

        result = self.scraper._merge_csv_chunks([
            csv_chunk(['2006', '2025', '2007'], [['A', 'x', '1', '..', '2'], ['B', 'x', '3', '..', '4']]),
            csv_chunk(['2024', '2025'], [['A', 'x', '5', '6'], ['B', 'x', '7', '8']]),
        ])

        rows = result.decode('utf-8-sig').splitlines()
        self.assertEqual(rows[2], 'regions,indicators,2006,2025,2007,2024,2025')
        self.assertEqual(rows[3:], ['A,x,1,..,2,5,6', 'B,x,3,..,4,7,8'])

    def test_merge_xlsx_chunks_preserves_headers_rows_and_numbers(self):
        def workbook_chunk(years, rows):
            workbook = Workbook()
            sheet = workbook.active
            sheet['A1'] = 'Large table'
            for column, value in enumerate([None] + years, 1):
                sheet.cell(3, column, value)
            for row_index, (category, values) in enumerate(rows, 4):
                sheet.cell(row_index, 1, category)
                for offset, value in enumerate(values, 2):
                    sheet.cell(row_index, offset, value)
                    sheet.cell(row_index, offset).number_format = '0.0'
            output = BytesIO()
            workbook.save(output)
            workbook.close()
            return output.getvalue()

        result = self.scraper._merge_xlsx_chunks([
            workbook_chunk(['2023'], [('A', [1]), ('B', [2])]),
            workbook_chunk(['2024', '2025'], [('A', [3, 4]), ('B', [5, 6])]),
        ])
        workbook = load_workbook(BytesIO(result))
        sheet = workbook.active

        self.assertEqual(sheet.max_row, 5)
        self.assertEqual(sheet.max_column, 4)
        self.assertEqual(
            [sheet.cell(3, column).value for column in range(1, 5)],
            [None, '2023', '2024', '2025'],
        )
        self.assertEqual(
            [sheet.cell(4, column).value for column in range(1, 5)],
            ['A', 1, 3, 4],
        )
        self.assertEqual(sheet.cell(4, 3).number_format, '0.0')
        workbook.close()


if __name__ == '__main__':
    unittest.main()
