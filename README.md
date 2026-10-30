# Statbank Parser

A command-line tool to extract data from Armenia's Statistical Committee database (https://statbank.armstat.am/pxweb/en/).

## Installation

1. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### List All Indicators

List all available tables (indicators) in the database:

```bash
python3 -m statbank_parser.cli list-indicators > indicators.jsonl
```

Output is in JSONL format (one JSON object per line) with fields:
- `id`: Table identifier (e.g., "EF-NA-01"); use `url` as the unique reference
- `title`: Table title
- `url`: Direct URL to the table
- `topic`: Main category
- `subtopics`: List of subcategories

Table URLs are deduplicated, and topic hierarchy is derived only from direct parent-child relations in the navigation tree.

### List Available Formats

See what file formats are available for a specific table:

```bash
python3 -m statbank_parser.cli list-formats --url "TABLE_URL"
```

Example:
```bash
python3 -m statbank_parser.cli list-formats --url "https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__1%20Econnomy%20and%20finance__15%20National%20Accounts/EF-NA-01.px/"
```

### Extract Data

Extract a complete table to CSV:

```bash
python3 -m statbank_parser.cli get-data --url "TABLE_URL" --output data.csv
```

Example:
```bash
python3 -m statbank_parser.cli get-data --url "https://statbank.armstat.am/pxweb/en/ArmStatBank/ArmStatBank__1%20Econnomy%20and%20finance__15%20National%20Accounts/EF-NA-01.px/" --output national_accounts.csv
```

For JSON output:
```bash
python3 -m statbank_parser.cli get-data --url "TABLE_URL" --output data.json
```

To download the original file produced by PXWeb, use `--format`:

```bash
python3 -m statbank_parser.cli get-data --url "TABLE_URL" --output data.csv --format csv
python3 -m statbank_parser.cli get-data --url "TABLE_URL" --output data.xlsx --format excel
python3 -m statbank_parser.cli get-data --url "TABLE_URL" --output data.json --format json-stat
```

Supported aliases are `csv`, `px`, `excel` (XLSX), `excel-xlsx`, `excel-xml`, `json`, `json-stat`, `json-stat2`, `html`, and `html5`. Exact format names returned by `list-formats` are also accepted.

## Publish to data.opendata.am

**The `publish` command creates and updates public datasets.** It publishes each row of `indicators.jsonl` as a separate dataset in the `opendataam` organization and `statistics` group. Every dataset has CSV, XLSX, and JSON-stat 2 resources. Dataset names include a hash of the source URL, so repeated table IDs do not collide.

Descriptions are generated from actual table metadata: dimensions, category counts, periods, units, source update time, and the number of CSV rows and columns. Existing datasets are patched in place, preserving their CKAN IDs and unchanged resources.

The completed publication contains **825 datasets and 2,475 resources**—825 files in each format. See [Data Catalog Armenia](https://data.opendata.am/) to browse the published datasets.

Validate the catalog without a token or any CKAN writes:

```bash
python3 -m statbank_parser.cli publish --dry-run
```

Set the CKAN API token without placing it in shell history:

```bash
read -s -p "CKAN API token: " CKAN_API_TOKEN; echo; export CKAN_API_TOKEN
```

Publish one table first to check permissions, metadata, and all three resources:

```bash
python3 -m statbank_parser.cli publish --limit 1
```

After checking the pilot dataset on the portal, publish the complete catalog:

```bash
python3 -m statbank_parser.cli publish
```

Downloaded source files are cached in `exports/`. Every processed table is appended to `publish-report.jsonl` with its status, CKAN URL, per-resource SHA-256, and any error. Rerun the same command after a failure: existing datasets and unchanged resources are reused, missing formats are added, failed uploads are retried, and changed local files update their existing resources instead of creating duplicates. The command exits nonzero if any table fails.

To fetch a newer version from Statbank rather than reuse the cache, remove the corresponding CSV, XLSX, and JSON files from `exports/` before rerunning the command.

## Features

- ✅ **List Indicators**: Recursively traverses the database and deduplicates table URLs
- ✅ **Extract Metadata**: Captures table ID and the correct topic hierarchy
- ✅ **List Formats**: Shows formats offered by the PXWeb result page
- ✅ **Complete Data Extraction**: Uses PXWeb file export instead of the size-limited HTML preview
- ✅ **Large Tables**: Selects hidden values through Advanced search and merges CSV, XLSX, and JSON-stat 2 chunks below the 100,000-cell limit
- ✅ **Rich CKAN Metadata**: Describes actual dimensions, periods, units, and tabular structure
- ✅ **JSONL Output**: Efficient line-by-line JSON format for indicators
- ✅ **Network Reliability**: Uses request timeouts and limited retries for temporary failures

## How It Works

The tool scrapes the PXWeb interface by:
1. **Traversing the Tree**: Follows only direct child categories in ASP.NET navigation postbacks
2. **Selecting Data**: Fetches table pages, extracts `__VIEWSTATE`, selects all variables, and uses Advanced search for large value sets
3. **Downloading Results**: Resolves the selected format's direct download URL and retrieves it in the same session
4. **Merging Large Exports**: Splits oversized selections and combines CSV, XLSX, and JSON-stat 2 chunks by their shared dimensions
5. **Parsing Default Output**: Reads the complete exported CSV into a Pandas DataFrame for CSV or JSON output

Commands return a nonzero exit code when network, parsing, or format selection fails.

## Testing

Run the test suite:

```bash
python -m unittest discover tests -v
```

See [tests/README.md](tests/README.md) for more details.

## Limitations

- Traversing all indicators can take several minutes due to the large number of tables
- Availability and export-size limits of the source PXWeb service still apply

## Project Structure

```
statbank-parser/
├── statbank_parser/
│   ├── __init__.py
│   ├── cli.py          # Command-line interface
│   ├── ckan.py         # CKAN API client and publication pipeline
│   └── scraper.py      # Web scraping logic
├── tests/
│   ├── __init__.py
│   ├── test_ckan.py    # CKAN publication tests
│   ├── test_cli.py     # CLI tests
│   └── test_scraper.py # Scraper tests
├── requirements.txt
├── setup.py
├── CHANGELOG.md
└── README.md
```

## License

MIT
