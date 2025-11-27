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
- `id`: Unique table identifier (e.g., "EF-NA-01")
- `title`: Table title
- `url`: Direct URL to the table
- `topic`: Main category
- `subtopics`: List of subcategories

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

Extract data from a table:

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

## Features

- ✅ **List Indicators**: Recursively traverses the database to find all tables
- ✅ **Extract Metadata**: Captures table ID, topic, and subtopic hierarchy
- ✅ **List Formats**: Shows available download formats for any table
- ✅ **Data Extraction**: Parses HTML tables and exports to CSV or JSON
- ✅ **JSONL Output**: Efficient line-by-line JSON format for indicators

## How It Works

The tool scrapes the PXWeb interface by:
1. **Traversing the Tree**: Simulates ASP.NET `__doPostBack` events to navigate categories
2. **Extracting Data**: Fetches table pages, extracts `__VIEWSTATE`, selects all variables, and submits forms
3. **Parsing Results**: Uses BeautifulSoup and Pandas to parse HTML tables

## Testing

Run the test suite:

```bash
python -m unittest discover tests -v
```

See [tests/README.md](tests/README.md) for more details.

## Limitations

- The `--format` option for downloading specific file formats (Excel, PX, etc.) is not currently functional due to the complexity of the ASP.NET postback mechanism
- The default HTML parsing works correctly and provides all data in CSV/JSON format
- Traversing all indicators can take several minutes due to the large number of tables

## Project Structure

```
statbank-parser/
├── statbank_parser/
│   ├── __init__.py
│   ├── cli.py          # Command-line interface
│   └── scraper.py      # Web scraping logic
├── tests/
│   ├── __init__.py
│   ├── test_cli.py     # CLI tests
│   └── test_scraper.py # Scraper tests
├── requirements.txt
├── setup.py
└── README.md
```

## License

MIT
