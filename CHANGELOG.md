# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CKAN publication pipeline for `data.opendata.am` with token-based authentication, permission checks, dry runs, per-table reports, and resumable uploads.
- Public dataset publication for all 825 Statbank tables with CSV, XLSX, and JSON-stat 2 resources.
- Rich CKAN descriptions generated from actual dimensions, periods, units, source updates, and CSV structure.
- Deterministic dataset and resource names, SHA-256 change detection, metadata patches, and stable CKAN IDs across reruns.
- Large-table export through PXWeb Advanced search and chunked merging for CSV, XLSX, and JSON-stat 2, including sparse missing-value statuses.
- Unit tests for source extraction, CKAN uploads, metadata updates, format merging, failure recovery, and CLI behavior.
- `openpyxl` dependency for preserving workbook values and styles during XLSX chunk merges.

### Changed

- Expanded PXWeb downloads beyond the size-limited HTML preview and refreshed the indicator catalog.
- Updated project documentation and test coverage guidance for the publication workflow.
- Removed generated sample CSV and HTML artifacts from version control.
