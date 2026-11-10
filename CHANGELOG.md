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

### Fixed

- JSON-stat 2 chunk merging put values and statuses in the wrong cells. The merge concatenated chunks that were split on the last dimension, but JSON-stat 2 stores values in row-major order. The merge now detects the split dimension from the chunk metadata and interleaves the chunk blocks for every combination of the other dimensions. This affected `IC-co-1-2024`, the only table above the 100,000-cell limit: only 24 of its 8,675 non-missing cells in the JSON-stat 2 export had the correct value. Its CSV and XLSX exports were correct.
- CSV chunk merging no longer fails when a category label repeats between chunks, for example the two `years` categories labelled `2025` in `IC-co-1-2024`. The stub columns are now the common leading header columns, not every column name that the chunks share.
