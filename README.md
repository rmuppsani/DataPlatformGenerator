# Databricks Data Platform Generator

Production-ready PySpark project template for building a configuration-driven Databricks data platform with the Medallion Architecture.

## What this project creates

- Bronze layer for raw Delta data
- Silver layer for validated and cleaned Delta data
- Quarantine area for invalid records
- Gold layer for fact tables, dimension tables, summary tables, and KPI tables
- Reusable utility modules
- Separate Bronze, Silver, and Gold pipeline entrypoints
- Configuration-driven source onboarding
- Unit tests for utility functions

## Project structure

```text
databricks_data_platform_generator/
├── AGENTS.md
├── README.md
├── config/
│   └── pipeline_config.json
├── notebooks/
│   ├── 01_bronze.py
│   ├── 02_silver.py
│   ├── 03_gold.py
│   └── 04_run_all.py
├── requirements.txt
├── pyproject.toml
├── src/
│   ├── pipelines/
│   │   ├── bronze.py
│   │   ├── silver.py
│   │   ├── gold.py
│   │   └── run_all.py
│   └── utils/
│       ├── config.py
│       ├── logger.py
│       ├── reader.py
│       ├── transformer.py
│       ├── validator.py
│       └── writer.py
└── tests/
    ├── test_config.py
    ├── test_reader.py
    └── test_validator.py
```

## Important Databricks note

A Databricks cloud cluster cannot directly read a Windows laptop path like:

```text
C:\Users\rmuppasani\Testing\POC\Test3\Source
```

Upload the files to DBFS, a Databricks Volume, or cloud storage first. The sample config expects:

```text
dbfs:/FileStore/Test3/Source
```

and writes to:

```text
dbfs:/FileStore/Test3/Target/Bronze
dbfs:/FileStore/Test3/Target/Silver
dbfs:/FileStore/Test3/Target/Quarantine
dbfs:/FileStore/Test3/Target/Gold
```

## Supported source formats

The reader automatically detects file type by extension:

- `.csv`
- `.json`
- `.parquet`
- `.xlsx`
- `.xls`

Excel files require the Databricks cluster library `com.crealytics:spark-excel` compatible with your Spark version.

## Configuration-driven onboarding

Add a new source by adding one object to `config/pipeline_config.json` under `sources`.

Each source controls:

- source path
- Bronze table/folder name
- Silver table/folder name
- reader options
- deduplication keys
- null defaults
- type casts
- data quality rules
- date/timestamp formats
- Gold fact/dimension/summary/KPI outputs

## Running in Databricks

1. Upload or sync this folder to Databricks Repos or Workspace files.
2. Upload source files to the configured DBFS path.
3. Update `repo_root` in each notebook:

```python
repo_root = "/Workspace/Repos/<user-or-team>/databricks_data_platform_generator"
```

4. Run either each layer separately:

```python
notebooks/01_bronze.py
notebooks/02_silver.py
notebooks/03_gold.py
```

or run the full pipeline:

```python
notebooks/04_run_all.py
```

## Running as Databricks jobs

Use these Python entrypoints:

```text
src/pipelines/bronze.py
src/pipelines/silver.py
src/pipelines/gold.py
src/pipelines/run_all.py
```

For production, pass the config path as a Databricks job parameter or adapt the `__main__` block to read a widget:

```python
dbutils.widgets.text("config_path", "config/pipeline_config.json")
config_path = dbutils.widgets.get("config_path")
```

## Bronze layer behavior

Bronze reads raw source files and writes Delta without modifying business data. It only adds metadata columns:

- `ingestion_timestamp`
- `source_file_name`
- `_source_file_name`

## Silver layer behavior

Silver applies configurable cleaning and validation:

- removes duplicates
- handles null values
- trims whitespace
- standardizes selected text columns
- standardizes date and timestamp columns
- validates data types
- applies data quality rules
- writes invalid records to quarantine

## Gold layer behavior

Gold creates:

- fact tables
- dimension tables
- sales summaries
- KPI tables
- monthly trend tables
- top customer tables

The sample `orders` config generates:

- `fact_orders`
- `dim_product`
- `dim_customer`
- `dim_payment_method`
- `sales_by_product`
- `sales_by_category`
- `sales_by_state`
- `payment_method_analysis`
- `top_customers`
- `kpi_sales`
- `monthly_sales_trend`

## Logging and error handling

The pipeline logs every major step as structured JSON:

- start and completion of each step
- record counts
- duration in seconds
- failure details

If one source fails, the pipeline logs the error and continues processing the next configured source.

## Optimization guidance

- Uses DataFrame operations rather than row-by-row Python logic.
- Uses `unionByName(..., allowMissingColumns=True)` for mixed schemas.
- Avoids caching by default.
- Supports partitioning per source where appropriate.
- Avoid high-cardinality partition columns.

## Local unit tests

Install dependencies:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest
```

Some runtime paths and Delta writes require Databricks or a Spark environment configured with Delta Lake.

## Local dashboard

A dependency-free local control room is available in `dashboard/`. It supports source upload, Bronze/Silver/Gold execution, layer status, validation checks, Gold product summaries, and an activity log. The local API writes refreshed outputs by default to `C:\Users\rmuppasani\Testing\POC\Test3\Target` with `Bronze`, `Silver`, and `Gold` subfolders. Set the `TARGET_DIR` environment variable to use another location.

Start it from the project root:

```powershell
python dashboard/server.py
```

Open `http://localhost:8002` in a browser. Choose an `.xlsx`, `.csv`, or `.json` source file and select **Run pipeline**. If no file is selected, the existing Bronze workbook is processed. Set the `PORT` environment variable to use a different port.
