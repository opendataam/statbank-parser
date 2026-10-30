import json
import os

import click

from .ckan import (
    CKANClient,
    RESOURCE_TYPES,
    dataset_name,
    load_indicators,
    publish_indicators,
    resource_name,
)
from .scraper import StatbankScraper

@click.group()
def cli():
    """CLI for scraping statbank.armstat.am"""
    pass

@cli.command()
def list_indicators():
    """List all available indicators (tables)"""
    scraper = StatbankScraper()
    try:
        indicators = scraper.get_indicators()
        for indicator in indicators:
            print(json.dumps(indicator, ensure_ascii=False))
    except Exception as e:
        raise click.ClickException(str(e)) from e

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
        raise click.ClickException(str(e)) from e

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
            with open(output, 'wb') as f:
                f.write(data)
        else:
            if output.endswith('.json'):
                data.to_json(output, orient='records', indent=2, force_ascii=False)
            else:
                data.to_csv(output, index=False)

        print(f"Data saved to {output}")
    except Exception as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.option('--indicators', default='indicators.jsonl', help='Input JSONL catalog')
@click.option('--data-dir', default='exports', help='Directory for downloaded CSV files')
@click.option('--report', default='publish-report.jsonl', help='JSONL publication report')
@click.option('--dry-run', is_flag=True, help='Validate metadata without network writes')
@click.option('--limit', type=click.IntRange(min=1), default=None, help='Publish only the first N tables')
def publish(indicators, data_dir, report, dry_run, limit):
    """Publish Statbank tables as public CKAN datasets"""
    try:
        selected = load_indicators(indicators)
        if limit:
            selected = selected[:limit]
        if dry_run:
            for indicator in selected:
                print(json.dumps({
                    'name': dataset_name(indicator),
                    'title': indicator['title'],
                    'source_url': indicator['url'],
                    'resources': [
                        resource_name(indicator, resource_type['extension'])
                        for resource_type in RESOURCE_TYPES
                    ],
                    'private': False,
                }, ensure_ascii=False))
            print(f'Validated {len(selected)} tables; no data was uploaded')
            return

        token = os.environ.get('CKAN_API_TOKEN')
        if not token:
            raise ValueError('CKAN_API_TOKEN environment variable is required')
        client = CKANClient(token)
        client.ensure_can_create_datasets()
        results = publish_indicators(
            selected,
            client,
            data_dir=data_dir,
            report_path=report,
        )
    except Exception as e:
        raise click.ClickException(str(e)) from e

    failures = [result for result in results if result['status'] == 'error']
    unchanged = [result for result in results if result['status'] == 'unchanged']
    print(
        f'Processed {len(results)} tables: {len(results) - len(failures) - len(unchanged)} '
        f'created/updated, {len(unchanged)} unchanged, {len(failures)} failed. '
        f'Report: {report}'
    )
    if failures:
        raise click.ClickException(
            f'{len(failures)} tables failed; rerun the command after resolving the report errors'
        )


if __name__ == '__main__':
    cli()
