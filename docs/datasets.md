# Input datasets

For manual record creation/editing, see [manual inputs](manual-inputs.md). Confirmed treatments appear in [project results](project-results.md); pending and in-progress records remain in the input queue.

1. Open a project and choose **Add input**. Define keys such as `supplier_name` and `document_type`, their description, text/number type, and whether a value is required. Keys use lowercase letters, digits and underscores, starting with a letter; they are unique per project. Reference the same keys in workflow instructions.
2. Choose **Upload input file**, name the dataset, and upload UTF-8 comma-separated CSV or a single-worksheet `.xlsx` workbook.
3. The first row must contain every defined input key exactly once, with no additional columns. Column order can differ. Required means each record needs a non-empty value; optional columns must still have headers.
4. Review the paginated table (50 records per page). Empty required values and invalid numbers show errors. Edit invalid pending rows in the dataset, or correct your source file and upload a new dataset.
5. Choose **Confirm dataset** when all records are valid. The dataset becomes available for reviewed robot execution; confirmation alone executes nothing. Reopen it from the project's dataset list after restarting Django.

Limits: 2 MB uploaded file, 1,000 data rows including blank rows, 30 inputs/columns, and 2,000 characters per cell. Completely blank rows are skipped. CSV uses UTF-8 (BOM accepted), commas and standard quoting. XLSX formulas and error cells are rejected; paste values before uploading. Multiple worksheets, legacy `.xls`, macros, encrypted workbooks, column mapping, and bulk deletion are outside this milestone. Individual input CRUD is available as described above.

Cells and headers are trimmed. Text identifiers preserve leading zeros when supplied as text; Excel numeric formatting is not preserved, so store identifiers as text cells. Numbers must be finite, at most 30 digits, with a decimal point and no thousands separators. Decimal values are stored as strings with the number type in the schema to avoid floating-point precision loss. Optional empty values are empty strings.

Parsed rows and a snapshot of their input definitions are stored in SQLite; the original upload is not retained. Later input edits do not rewrite historical datasets. The preview warns when current project definitions differ from its snapshot. Dataset preview/ready states describe preparation; row processing states and attempts are tracked separately by the runner.

Never upload credentials. Importing does not evaluate formulas or execute CSV cell content. Read-only Django admin views are available for input definitions, datasets and rows. Both runtime lock files include the XLSX reader and XML parser protection.

Download record and final run outputs as CSV or XLSX from [project results](project-results.md). Downloads include all matching attempts across pages and respect the selected filters.
