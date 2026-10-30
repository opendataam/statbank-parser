import csv
import json
import logging
import math
from copy import copy, deepcopy
from io import BytesIO, StringIO
from urllib.parse import quote, unquote, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StatbankScraper:
    BASE_URL = 'https://statbank.armstat.am/pxweb/en/ArmStatBank/'
    DEFAULT_TIMEOUT = (10, 60)
    FORMAT_ALIASES = {
        'csv': 'Comma delimited with heading',
        'px': 'PX-file',
        'excel': 'Excel (xlsx)',
        'excel-xlsx': 'Excel (xlsx)',
        'excel-xml': 'Excel workbook (xml)',
        'json': 'Json file (json)',
        'json-stat': 'JSON-stat file (json)',
        'json-stat2': 'JSON-stat 2 file (json)',
        'html': 'Html file (htm)',
        'html5': 'Html5 table (htm)',
    }

    def __init__(self, timeout=DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.session = requests.Session()
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(('GET', 'POST')),
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount('https://', adapter)
        self.session.mount('http://', adapter)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def get_indicators(self):
        """Return all tables with unique URLs and their category hierarchy."""
        self.visited = set()
        items = self._traverse_category(self.BASE_URL, [])
        unique_items = []
        seen_urls = set()
        for item in items:
            if item['url'] in seen_urls:
                continue
            seen_urls.add(item['url'])
            unique_items.append(item)
        return unique_items

    def _traverse_category(self, url, breadcrumbs, node_path='ArmStatBank'):
        if url in self.visited:
            return []
        self.visited.add(url)

        logger.info('Visiting category: %s', url)
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        content_area = soup.find('div', id='pxwebcontent')
        if not content_area:
            content_area = soup.body
        if not content_area:
            raise ValueError(f'Could not find page content for {url}')

        links = content_area.find_all('a')
        logger.info('Found %d links in content area', len(links))
        items = []
        current_path = unquote(urlparse(url).path).rstrip('/')

        for link in links:
            href = link.get('href', '')
            text = link.get_text(strip=True)
            if not href:
                continue

            if href.lower().endswith(('.px', '.px/')):
                full_url = urljoin(url, href)
                table_path = unquote(urlparse(full_url).path).rstrip('/')
                if table_path.rsplit('/', 1)[0] != current_path:
                    continue

                filename = table_path.rsplit('/', 1)[-1]
                table_id = filename.rsplit('.', 1)[0]
                items.append({
                    'id': table_id,
                    'title': text,
                    'url': full_url,
                    'topic': breadcrumbs[0] if breadcrumbs else '',
                    'subtopics': breadcrumbs[1:],
                })
            elif 'javascript:__doPostBack' in href:
                args = href.split("'")
                if len(args) < 4:
                    continue
                target = args[1]
                argument = args[3]
                if 'MenuNavigationTree' not in target:
                    continue

                parts = argument.split('\\\\')
                if len(parts) == 1:
                    parts = argument.split('\\')
                last_part = parts[-1]
                if last_part.startswith('pArmStatBank'):
                    last_part = last_part[1:]

                path_parts = last_part.rsplit('__', 1)
                if len(path_parts) != 2:
                    raise ValueError(f'Invalid navigation path: {last_part}')
                if path_parts[0] != node_path:
                    continue

                new_url = f'{self.BASE_URL}{quote(last_part)}'
                items.extend(self._traverse_category(
                    new_url,
                    breadcrumbs + [text],
                    node_path=last_part,
                ))

        return items

    def get_available_formats(self, table_url):
        """Return the file formats available for a table."""
        logger.info('Fetching available formats for: %s', table_url)
        _, result_soup = self._get_table_result(table_url)
        return [label for label, _ in self._get_format_options(result_soup)]

    def get_table_data(self, table_url, file_format=None):
        """Return a complete DataFrame or the bytes of a selected file format."""
        logger.info('Fetching data for: %s (Format: %s)', table_url, file_format)
        post_response, result_soup = self._get_table_result(table_url)
        if self._get_format_options(result_soup):
            content = self._download_format(
                post_response,
                result_soup,
                file_format or 'csv',
            )
        else:
            content = self._get_large_table_data(table_url, file_format or 'csv')
        if file_format:
            return content
        return pd.read_csv(
            BytesIO(content),
            skiprows=2,
            encoding='utf-8-sig',
        )

    def _get_table_page(self, table_url):
        response = self.session.get(table_url, timeout=self.timeout)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        if not soup.find('form', id='aspnetForm'):
            raise ValueError('Could not find aspnetForm')
        if not soup.find('input', id='__VIEWSTATE') or not soup.find('input', id='__EVENTVALIDATION'):
            raise ValueError('Could not find ASP.NET form state')
        return response, soup

    def _get_table_result(self, table_url):
        response, soup = self._get_table_page(table_url)
        data = {
            '__VIEWSTATE': soup.find('input', id='__VIEWSTATE')['value'],
            '__EVENTVALIDATION': soup.find('input', id='__EVENTVALIDATION')['value'],
        }
        button = soup.find('input', {'type': 'submit', 'value': 'Continue'})
        if not button:
            button = soup.find('input', {'type': 'submit', 'value': 'Show table'})
        if not button:
            button = soup.find('input', {'type': 'submit', 'class': 'pxweb-btn-action'})

        if button:
            data[button['name']] = button['value']
        else:
            data['ctl00$ContentPlaceHolderMain$VariableSelector1$VariableSelector1$ButtonViewTable'] = 'Show table'

        for select in soup.find_all('select'):
            if not select.get('name'):
                continue
            data[select['name']] = [
                option['value']
                for option in select.find_all('option')
                if option.has_attr('value')
            ]

        post_response = self.session.post(
            response.url,
            data=data,
            timeout=self.timeout,
        )
        post_response.raise_for_status()
        return post_response, BeautifulSoup(post_response.content, 'html.parser')

    @staticmethod
    def _get_form_data(soup):
        data = {}
        for field in soup.find_all('input', type='hidden'):
            if field.get('name'):
                data[field['name']] = field.get('value', '')
        for select in soup.find_all('select'):
            if not select.get('name'):
                continue
            values = [
                option['value']
                for option in select.find_all('option')
                if option.has_attr('selected') and option.has_attr('value')
            ]
            if values:
                data[select['name']] = values
        return data

    def _submit_form_button(self, table_url, soup, button_name, selections=None):
        button = next(
            (
                item
                for item in soup.find_all('input')
                if button_name in (item.get('name') or '')
            ),
            None,
        )
        if not button:
            raise ValueError(f'Could not find form button {button_name}')
        data = self._get_form_data(soup)
        data.update(selections or {})
        data[button['name']] = button.get('value', '')
        response = self.session.post(table_url, data=data, timeout=self.timeout)
        response.raise_for_status()
        return response, BeautifulSoup(response.content, 'html.parser')

    def _select_large_values(self, table_url):
        response, soup = self._get_table_page(table_url)
        processed_targets = set()
        for _ in range(10):
            advanced = None
            for link in soup.find_all('a'):
                if 'Advanced search' not in link.get_text():
                    continue
                href = link.get('href', '')
                args = href.split("'")
                if 'javascript:__doPostBack' not in href or len(args) < 4:
                    raise ValueError('Could not open advanced variable search')
                if args[1] not in processed_targets:
                    advanced = link
                    break
            if not advanced:
                return response, soup
            processed_targets.add(args[1])
            data = self._get_form_data(soup)
            data['__EVENTTARGET'] = args[1]
            data['__EVENTARGUMENT'] = ''
            response = self.session.post(response.url, data=data, timeout=self.timeout)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            response, soup = self._submit_form_button(
                response.url,
                soup,
                'FetchAllButton',
            )
            results = next(
                (
                    select
                    for select in soup.find_all('select')
                    if 'SearchResults' in (select.get('name') or '')
                ),
                None,
            )
            if results and results.find_all('option'):
                response, soup = self._submit_form_button(
                    response.url,
                    soup,
                    'MoveToResultButton',
                    {
                        results['name']: [
                            option['value'] for option in results.find_all('option')
                        ],
                    },
                )
            selected = next(
                (
                    select
                    for select in soup.find_all('select')
                    if 'SelectedVariableValues' in (select.get('name') or '')
                ),
                None,
            )
            if not selected or not selected.find_all('option'):
                raise ValueError('Advanced search returned no variable values')
            response, soup = self._submit_form_button(
                response.url,
                soup,
                'DoneButton',
                {
                    selected['name']: [
                        option['value'] for option in selected.find_all('option')
                    ],
                },
            )
        raise ValueError('Too many large variables in table')

    def _get_large_table_data(self, table_url, file_format, max_cells=100000):
        response, soup = self._select_large_values(table_url)
        selects = [
            select
            for select in soup.find_all('select')
            if select.get('name') and select.find_all('option')
        ]
        if not selects:
            raise ValueError('No variable values available for large-table export')
        values = [
            [option['value'] for option in select.find_all('option')]
            for select in selects
        ]
        total_cells = math.prod(len(variable_values) for variable_values in values)
        chunk_index = len(selects) - 1
        requested = file_format.strip().lower()
        merge_formats = {
            'csv': self._merge_csv_chunks,
            'comma delimited with heading': self._merge_csv_chunks,
            'json-stat2': self._merge_json_stat2_chunks,
            'json-stat 2 file (json)': self._merge_json_stat2_chunks,
            'excel': self._merge_xlsx_chunks,
            'excel-xlsx': self._merge_xlsx_chunks,
            'excel (xlsx)': self._merge_xlsx_chunks,
        }
        if total_cells <= max_cells:
            chunks = [values[chunk_index]]
        else:
            if requested not in merge_formats:
                raise ValueError(
                    'Chunked large-table export supports only CSV, XLSX, and JSON-stat 2'
                )
            chunk_size = None
            for index in range(len(selects) - 1, -1, -1):
                other_cells = math.prod(
                    len(variable_values)
                    for variable_index, variable_values in enumerate(values)
                    if variable_index != index
                )
                if other_cells <= max_cells:
                    chunk_index = index
                    chunk_size = max_cells // other_cells
                    break
            if not chunk_size:
                raise ValueError('Cannot split table below the 100,000-cell source limit')
            if chunk_index != len(selects) - 1:
                raise ValueError('Chunked export requires splitting the last table dimension')
            chunks = [
                values[chunk_index][start:start + chunk_size]
                for start in range(0, len(values[chunk_index]), chunk_size)
            ]

        contents = []
        for chunk in chunks:
            selections = {
                select['name']: variable_values
                for select, variable_values in zip(selects, values)
            }
            selections[selects[chunk_index]['name']] = chunk
            post_response, result_soup = self._submit_form_button(
                response.url,
                soup,
                'ButtonViewTable',
                selections,
            )
            contents.append(self._download_format(post_response, result_soup, file_format))
        if len(contents) == 1:
            return contents[0]
        return merge_formats[requested](contents)

    @staticmethod
    def _merge_csv_chunks(contents):
        tables = []
        for content in contents:
            rows = list(csv.reader(StringIO(content.decode('utf-8-sig'))))
            if len(rows) < 4:
                raise ValueError('Invalid CSV chunk returned by Statbank')
            title, header, data = rows[0], rows[2], rows[3:]
            if not header or any(len(row) != len(header) for row in data):
                raise ValueError('Inconsistent CSV chunk returned by Statbank')
            tables.append((title, header, data))

        first_header = tables[0][1]
        if len(set(first_header)) != len(first_header):
            raise ValueError('Cannot merge CSV chunks with duplicate column names')
        shared_headers = set(first_header).intersection(
            *(set(header) for _, header, _ in tables[1:])
        )
        key_columns = [column for column in first_header if column in shared_headers]
        if not key_columns:
            raise ValueError('Cannot identify shared columns between CSV chunks')
        combined_header = list(first_header)
        combined_rows = [list(row) for row in tables[0][2]]
        first_keys = [
            [row[first_header.index(column)] for column in key_columns]
            for row in tables[0][2]
        ]
        for title, header, rows in tables[1:]:
            if title != tables[0][0] or len(rows) != len(combined_rows):
                raise ValueError('CSV chunks do not describe the same table rows')
            if len(set(header)) != len(header):
                raise ValueError('Cannot merge CSV chunks with duplicate column names')
            keys = [
                [row[header.index(column)] for column in key_columns]
                for row in rows
            ]
            if keys != first_keys:
                raise ValueError('CSV chunks have different row ordering or dimensions')
            extra_indices = [
                index
                for index, column in enumerate(header)
                if column not in key_columns
            ]
            if not extra_indices:
                raise ValueError('CSV chunks do not contain additional data columns')
            combined_header.extend(header[index] for index in extra_indices)
            for combined_row, row in zip(combined_rows, rows):
                combined_row.extend(row[index] for index in extra_indices)

        output = StringIO()
        writer = csv.writer(output, lineterminator='\r\n')
        writer.writerow(tables[0][0])
        writer.writerow([])
        writer.writerow(combined_header)
        writer.writerows(combined_rows)
        return output.getvalue().encode('utf-8-sig')

    @staticmethod
    def _merge_json_stat2_chunks(contents):
        datasets = [json.loads(content) for content in contents]
        first = datasets[0]
        if not first.get('id') or not first.get('size') or len(first['id']) != len(first['size']):
            raise ValueError('Invalid JSON-stat 2 chunk')
        dimension_id = first['id'][-1]
        for dataset in datasets[1:]:
            if dataset.get('id') != first['id']:
                raise ValueError('JSON-stat 2 chunks have different dimensions')
            for key in set(first) | set(dataset):
                if key not in {'dimension', 'size', 'value', 'status'}:
                    if first.get(key) != dataset.get(key):
                        raise ValueError(f'JSON-stat 2 chunks differ in {key}')
            for index, current_id in enumerate(first['id'][:-1]):
                if dataset['size'][index] != first['size'][index]:
                    raise ValueError('JSON-stat 2 chunks have different dimension sizes')
                if dataset['dimension'][current_id] != first['dimension'][current_id]:
                    raise ValueError('JSON-stat 2 chunks have different dimension metadata')

        merged = deepcopy(first)
        merged['size'][-1] = sum(dataset['size'][-1] for dataset in datasets)
        combined_index = {}
        combined_category = {}
        for dataset in datasets:
            category = dataset['dimension'][dimension_id]['category']
            index = category.get('index')
            if not isinstance(index, dict):
                raise ValueError('Expected dictionary category indexes in JSON-stat 2')
            for code, _ in sorted(index.items(), key=lambda item: item[1]):
                if code in combined_index:
                    raise ValueError(f'Duplicate category {code} in JSON-stat 2 chunks')
                combined_index[code] = len(combined_index)
            for key, value in category.items():
                if key == 'index':
                    continue
                if key not in combined_category:
                    combined_category[key] = {} if isinstance(value, dict) else [] if isinstance(value, list) else value
                if isinstance(value, dict):
                    combined_category[key].update(value)
                elif isinstance(value, list):
                    combined_category[key].extend(value)
                elif combined_category[key] != value:
                    raise ValueError(f'JSON-stat 2 chunks differ in category {key}')
        combined_category['index'] = combined_index
        merged['dimension'][dimension_id]['category'] = combined_category

        for field in ('value', 'status'):
            if not any(field in dataset for dataset in datasets):
                continue
            if all(isinstance(dataset.get(field), list) for dataset in datasets):
                merged[field] = [
                    item
                    for dataset in datasets
                    for item in dataset[field]
                ]
                continue
            combined_values = {}
            offset = 0
            for dataset in datasets:
                values = dataset.get(field, {})
                if not isinstance(values, dict):
                    raise ValueError(f'Cannot combine JSON-stat 2 {field} representations')
                for key, value in values.items():
                    combined_values[str(offset + int(key))] = value
                offset += math.prod(dataset['size'])
            merged[field] = combined_values
        return json.dumps(merged, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    @staticmethod
    def _merge_xlsx_chunks(contents):
        workbooks = [load_workbook(BytesIO(content)) for content in contents]
        sheets = [workbook.active for workbook in workbooks]
        first = sheets[0]
        headers = [
            [sheet.cell(3, column).value for column in range(1, sheet.max_column + 1)]
            for sheet in sheets
        ]
        key_counts = []
        for header in headers:
            key_count = next(
                (index for index, value in enumerate(header) if value not in (None, '')),
                len(header),
            )
            if not key_count or key_count == len(header):
                raise ValueError('Cannot identify dimension and data columns in XLSX chunks')
            if len(set(header[key_count:])) != len(header[key_count:]):
                raise ValueError('Cannot merge XLSX chunks with duplicate data columns')
            key_counts.append(key_count)
        if len(set(key_counts)) != 1:
            raise ValueError('XLSX chunks have different dimension column counts')
        key_count = key_counts[0]
        if any(sheet.max_row != first.max_row for sheet in sheets[1:]):
            raise ValueError('XLSX chunks have different row counts')
        first_keys = [
            tuple(first.cell(row, column).value for column in range(1, key_count + 1))
            for row in range(4, first.max_row + 1)
        ]
        for sheet in sheets[1:]:
            if sheet.cell(1, 1).value != first.cell(1, 1).value:
                raise ValueError('XLSX chunks have different table titles')
            keys = [
                tuple(sheet.cell(row, column).value for column in range(1, key_count + 1))
                for row in range(4, sheet.max_row + 1)
            ]
            if keys != first_keys:
                raise ValueError('XLSX chunks have different row ordering or dimensions')
            extra_indices = range(key_count + 1, sheet.max_column + 1)
            target_start = first.max_column + 1
            for offset, source_index in enumerate(extra_indices):
                target_index = target_start + offset
                for row in range(3, first.max_row + 1):
                    source = sheet.cell(row, source_index)
                    destination = first.cell(row, target_index)
                    destination.value = source.value
                    if source.has_style:
                        destination._style = copy(source._style)
                source_letter = get_column_letter(source_index)
                target_letter = get_column_letter(target_index)
                first.column_dimensions[target_letter].width = sheet.column_dimensions[source_letter].width

        output = BytesIO()
        workbooks[0].save(output)
        for workbook in workbooks:
            workbook.close()
        return output.getvalue()

    @staticmethod
    def _get_format_options(result_soup):
        options = []
        for label in result_soup.find_all('label'):
            input_id = label.get('for', '')
            if 'SaveAsRadioButtonList' not in input_id:
                continue
            radio = result_soup.find('input', id=input_id)
            if radio and radio.get('value'):
                options.append((label.get_text(strip=True), radio['value']))
        return options

    def _download_format(self, post_response, result_soup, file_format):
        options = self._get_format_options(result_soup)
        requested = file_format.strip().lower()
        expected_label = self.FORMAT_ALIASES.get(requested)
        target_value = None
        for label, value in options:
            if label.lower() == requested or label == expected_label:
                target_value = value
                break

        if not target_value:
            available = ', '.join(label for label, _ in options)
            aliases = ', '.join(sorted(self.FORMAT_ALIASES))
            raise ValueError(
                f"Format '{file_format}' not found. "
                f'Available aliases: {aliases}. Available formats: {available}'
            )

        download_url = urljoin(post_response.url, target_value)
        logger.info('Downloading format: %s', file_format)
        response = self.session.get(download_url, timeout=self.timeout)
        response.raise_for_status()
        return response.content
