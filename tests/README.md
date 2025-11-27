# Tests

This directory contains unit tests for the statbank-parser project.

## Running Tests

To run all tests:

```bash
python -m unittest discover tests -v
```

To run a specific test file:

```bash
python -m unittest tests.test_scraper -v
python -m unittest tests.test_cli -v
```

To run a specific test case:

```bash
python -m unittest tests.test_scraper.TestStatbankScraper.test_init -v
```

## Test Coverage

### test_scraper.py
Tests for the `StatbankScraper` class:
- **test_init**: Verifies scraper initialization
- **test_traverse_category_with_tables**: Tests table discovery in categories
- **test_traverse_category_with_postback**: Tests handling of ASP.NET PostBack links
- **test_get_available_formats**: Tests format list retrieval
- **test_get_table_data_default**: Tests HTML table parsing
- **test_get_indicators_initializes_visited**: Tests visited set initialization
- **test_traverse_category_prevents_infinite_loops**: Tests cycle prevention
- **test_extract_id_from_url_***: Tests table ID extraction logic

### test_cli.py
Tests for CLI commands:
- **test_list_indicators_command**: Tests JSONL output format
- **test_list_formats_command**: Tests format listing
- **test_get_data_command_default_csv**: Tests CSV data extraction
- **test_get_data_command_json_output**: Tests JSON data extraction
- **test_get_data_command_with_format**: Tests format download option
- **test_*_error_handling**: Tests error handling for all commands
- **test_cli_group_exists**: Tests CLI help functionality

## Test Structure

Tests use:
- `unittest` framework (Python standard library)
- `unittest.mock` for mocking HTTP requests and responses
- `click.testing.CliRunner` for testing CLI commands
- Isolated filesystem for file I/O tests

## Mocking Strategy

The tests mock:
- HTTP requests (`requests.Session.get` and `.post`)
- HTML responses with BeautifulSoup-parseable content
- Pandas DataFrames for table data
- File system operations where appropriate

This ensures tests run quickly without making actual network requests to the statbank.armstat.am website.
