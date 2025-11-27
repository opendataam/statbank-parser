import click
from .scraper import StatbankScraper
import json

@click.group()
def cli():
    """CLI for scraping statbank.armstat.am"""
    pass

@cli.command()
def list_indicators():
    """List all available indicators (tables)"""
    scraper = StatbankScraper()
    indicators = scraper.get_indicators()
    for indicator in indicators:
        print(json.dumps(indicator, ensure_ascii=False))

@cli.command()
@click.option('--url', required=True, help='URL of the table')
def list_formats(url):
    """List available file formats for a table"""
    scraper = StatbankScraper()
    try:
        formats = scraper.get_available_formats(url)
        print("Available formats:")
        for fmt in formats:
            print(f"  - {fmt}")
    except Exception as e:
        print(f"Error: {e}")

@cli.command()
@click.option('--url', required=True, help='URL of the table to scrape')
@click.option('--output', default='output.csv', help='Output file path')
@click.option('--format', default=None, help='File format to download (e.g., excel, csv, px, json-stat)')
def get_data(url, output, format):
    """Get data for a specific table"""
    scraper = StatbankScraper()
    try:
        data = scraper.get_table_data(url, file_format=format)
        
        if format:
            # Data is bytes
            with open(output, 'wb') as f:
                f.write(data)
        else:
            # Data is DataFrame
            if output.endswith('.json'):
                data.to_json(output, orient='records', indent=2, force_ascii=False)
            else:
                data.to_csv(output, index=False)
                
        print(f"Data saved to {output}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    cli()
