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
python -m unittest tests.test_ckan -v
```

To run a specific test case:

```bash
python -m unittest tests.test_scraper.TestStatbankScraper.test_init -v
```

## Test Coverage

### test_scraper.py
Tests for the `StatbankScraper` class:
- **test_init**: Verifies timeout and retry configuration
- **test_traverse_category_with_tables**: Tests table and ID discovery
- **test_traverse_category_uses_only_direct_children**: Tests sibling filtering and correct topic hierarchy
- **test_get_available_formats**: Tests format list retrieval and form selection
- **test_get_table_data_default_downloads_complete_csv**: Tests real CSV parsing beyond 30 data columns
- **test_get_table_data_format_aliases_use_direct_download**: Tests CSV, JSON-stat, and XLSX aliases with one POST and a direct download GET
- **test_get_table_data_rejects_unknown_format**: Tests actionable format errors
- **test_get_table_data_uses_large_table_fallback**: Tests fallback when the initial result has no export formats
- **test_select_large_values_uses_advanced_search**: Tests hidden-value selection and repeated Advanced search links
- **test_large_table_within_limit_selects_every_value**: Tests complete selection for large tables within the cell limit
- **test_large_table_chunks_and_merges_csv_without_losing_values**: Tests chunked export, shared dimensions, and preservation of `..` values
- **test_merge_json_stat2_chunks_preserves_values_and_sparse_status**: Tests category merging and sparse-status index offsets
- **test_merge_xlsx_chunks_preserves_headers_rows_and_numbers**: Tests blank dimension headers, row alignment, numbers, and styles
- **test_get_indicators_initializes_visited_and_deduplicates_urls**: Tests cycle state and URL deduplication
- **test_traverse_category_prevents_infinite_loops**: Tests cycle prevention
- **test_traverse_category_does_not_hide_network_errors**: Tests propagation of request failures

### test_cli.py
Tests for CLI commands:
- **test_list_indicators_command**: Tests JSONL output format
- **test_list_formats_command**: Tests format listing
- **test_get_data_command_default_csv**: Tests CSV data extraction
- **test_get_data_command_json_output**: Tests JSON data extraction
- **test_get_data_command_with_format**: Tests binary format output
- **test_*_error_handling**: Tests nonzero exit codes and error messages for all commands
- **test_cli_group_exists**: Tests CLI help functionality

### test_ckan.py
Tests for CKAN publication:
- Deterministic names, duplicate-ID handling, and public dataset metadata
- Rich descriptions with dimensions, periods, units, source updates, and CSV structure
- CKAN HTTP errors, authorization preflight, and multipart uploads
- Three-format dataset creation and adding XLSX/JSON-stat 2 to existing CSV cards
- Metadata patches with stable package/resource IDs, unchanged resume, and updates without duplicates
- Per-table error reporting and continued batch processing
- CLI dry-run, missing-token handling, and partial-failure exit status

## Test Structure

Tests use:
- `unittest` framework (Python standard library)
- `unittest.mock` for mocking HTTP requests and responses
- Real Pandas parsing of CSV fixture bytes
- `click.testing.CliRunner` for testing CLI commands
- Isolated filesystem for file I/O tests

## Mocking Strategy

The tests mock HTTP requests (`requests.Session.get` and `.post`) and return BeautifulSoup-parseable HTML or file bytes. DataFrame parsing and output-file serialization run without mocks.

This ensures tests run quickly without making actual network requests to the statbank.armstat.am website. Live source checks are performed separately from the unit suite.
