---
name: docx
description: Read, write, convert, and template-fill DOCX/PDF/XLSX documents
argument-hint: "read <file> | write <file> | convert <input> <output> | template <template> <data> | help"
user-invocable: true
context: fork
when_to_use: "When you need to read content from DOCX/PDF/XLSX files, generate DOCX from markdown, convert between document formats, or fill DOCX templates with data"
---

# Document Processing Skill

When invoked, immediately output: **SKILL_STARTED:** docx

Process Word, PDF, and Excel documents -- read content, generate documents, convert formats, fill templates.

## Commands

| Command | Description |
|---------|-------------|
| `/docx read <file>` | Extract text/markdown from DOCX/PDF/XLSX |
| `/docx write <file>` | Create DOCX from markdown content (via stdin or file) |
| `/docx convert <input> <output>` | Convert between formats (docx→pdf, xlsx→csv) |
| `/docx template <template> <data.json>` | Fill DOCX template with JSON data |
| `/docx help` | Show usage |

## Argument Reference

| Command | Arguments | Example |
|---------|-----------|---------|
| `read` | `<filepath>` | `/docx read contract.docx` |
| `write` | `<output-file> [--input <md-file>]` | `/docx write report.docx --input draft.md` |
| `convert` | `<input> <output>` | `/docx convert data.xlsx data.csv` |
| `template` | `<template.docx> <data.json>` | `/docx template invoice.docx orders.json` |

## Detailed Workflow

### Read Documents

Extract content from DOCX, PDF, or XLSX files:

```bash
/docx read document.docx    # → Markdown output
/docx read report.pdf       # → Plain text output
/docx read data.xlsx        # → CSV-style table output
```

**Output format:**
- DOCX → Markdown with headings, lists, tables preserved
- PDF → Plain text with basic formatting
- XLSX → CSV-style tables with sheet names

**Use when:**
- Analyzing contract documents
- Extracting data from reports
- Reading spreadsheet data
- Processing uploaded documents

### Write Documents

Generate DOCX from markdown:

```bash
/docx write output.docx --input notes.md
# Or pipe content:
echo "# Title\nContent" | python scripts/docx.py write output.docx
```

**Supported markdown:**
- Headings (H1-H6)
- Bold, italic, code
- Lists (ordered, unordered)
- Tables
- Paragraphs

**Use when:**
- Generating reports from data
- Creating formatted documents
- Exporting markdown notes

### Convert Formats

Convert between document formats:

```bash
/docx convert input.xlsx output.csv      # Excel → CSV
/docx convert input.docx output.pdf      # Word → PDF (requires LibreOffice)
/docx convert input.pdf output.txt       # PDF → Text
```

**Supported conversions:**
- `xlsx` → `csv` (native Python)
- `docx` → `pdf` (requires LibreOffice/unoconv)
- `pdf` → `txt` (text extraction)
- `docx` → `txt` (text extraction)

**Use when:**
- Preparing data for import
- Converting for different platforms
- Extracting text from binary formats

### Template Filling

Fill DOCX templates with JSON data:

```bash
/docx template invoice-template.docx customer-data.json
```

**Template syntax:**
Use `{{variable}}` placeholders in DOCX template:

```
Invoice for {{customer_name}}
Amount: ${{amount}}
Date: {{date}}
```

**JSON data:**
```json
{
  "customer_name": "Acme Corp",
  "amount": "1,250.00",
  "date": "2026-02-14"
}
```

**Use when:**
- Generating invoices
- Creating personalized documents
- Mail merge operations

## Dependencies

**Required:**
- `python-docx` - DOCX read/write
- `openpyxl` - XLSX processing
- `PyPDF2` or `pypdf` - PDF reading

**Optional:**
- `LibreOffice` or `unoconv` - For DOCX→PDF conversion

**Install:**
```bash
pip install python-docx openpyxl pypdf
```

## Implementation

```bash
python ~/.claude/skills/docx/scripts/docx.py <command> [args]
```

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| **Module not found** | Missing python-docx/openpyxl/pypdf | Run `pip install python-docx openpyxl pypdf` |
| **File not found** | Invalid file path | Check file exists and path is correct |
| **Unsupported format** | Unknown file extension | Use supported formats: docx, pdf, xlsx, csv, txt |
| **Template error** | Missing placeholder data | Ensure JSON has all template variables |
| **Conversion failed** | LibreOffice not installed | Install LibreOffice for advanced conversions |

## Examples

**Extract contract terms:**
```bash
/docx read vendor-contract.docx
# → Returns markdown with sections, clauses, signatures
```

**Generate weekly report:**
```bash
/docx write weekly-report.docx --input report-draft.md
# → Creates formatted DOCX from markdown notes
```

**Convert Excel to CSV:**
```bash
/docx convert sales-data.xlsx sales-data.csv
# → Extracts all sheets as CSV
```

**Fill invoice template:**
```bash
/docx template invoice.docx customer-123.json
# → Generates invoice-customer-123.docx
```

## When to Use

Use `/docx` when you need to:
- ✅ Read content from uploaded DOCX/PDF/XLSX files
- ✅ Generate formatted Word documents from markdown
- ✅ Convert between document formats (xlsx→csv, docx→pdf)
- ✅ Fill document templates with data (invoices, contracts, reports)
- ✅ Extract text from binary document formats
- ✅ Automate document generation workflows

Do NOT use when:
- ❌ Editing existing DOCX structure (use LibreOffice API instead)
- ❌ Advanced PDF manipulation (use PyMuPDF/pdftk)
- ❌ Image extraction from documents (use python-docx + PIL)
