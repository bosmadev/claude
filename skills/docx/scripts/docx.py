#!/usr/bin/env python3
"""
Document processing skill - read, write, convert DOCX/PDF/XLSX files.
Usage: python docx.py <command> [args]
"""

import sys
import json
from pathlib import Path


def check_dependencies():
    """Check if required packages are installed."""
    missing = []
    try:
        import docx
    except ImportError:
        missing.append("python-docx")

    try:
        import openpyxl
    except ImportError:
        missing.append("openpyxl")

    try:
        import pypdf
    except ImportError:
        try:
            import PyPDF2
        except ImportError:
            missing.append("pypdf (or PyPDF2)")

    if missing:
        print(f"❌ Missing dependencies: {', '.join(missing)}", file=sys.stderr)
        print(f"   Run: pip install {' '.join(missing)}", file=sys.stderr)
        return False
    return True


def cmd_read(file_path):
    """Read content from DOCX/PDF/XLSX and output as text/markdown."""
    path = Path(file_path)
    if not path.exists():
        print(f"❌ File not found: {file_path}", file=sys.stderr)
        return 1

    ext = path.suffix.lower()

    try:
        if ext == ".docx":
            return read_docx(path)
        elif ext == ".pdf":
            return read_pdf(path)
        elif ext in [".xlsx", ".xls"]:
            return read_xlsx(path)
        else:
            print(f"❌ Unsupported format: {ext}", file=sys.stderr)
            print("   Supported: .docx, .pdf, .xlsx", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"❌ Error reading {file_path}: {e}", file=sys.stderr)
        return 1


def read_docx(path):
    """Extract markdown from DOCX."""
    from docx import Document

    doc = Document(str(path))
    lines = []

    for para in doc.paragraphs:
        style = para.style.name.lower()
        text = para.text.strip()

        if not text:
            lines.append("")
            continue

        # Convert headings
        if "heading 1" in style:
            lines.append(f"# {text}")
        elif "heading 2" in style:
            lines.append(f"## {text}")
        elif "heading 3" in style:
            lines.append(f"### {text}")
        elif "heading 4" in style:
            lines.append(f"#### {text}")
        elif "heading 5" in style:
            lines.append(f"##### {text}")
        elif "heading 6" in style:
            lines.append(f"###### {text}")
        else:
            lines.append(text)

    # Extract tables
    for table in doc.tables:
        lines.append("")
        for i, row in enumerate(table.rows):
            cells = [cell.text.strip() for cell in row.cells]
            lines.append("| " + " | ".join(cells) + " |")
            if i == 0:  # Header separator
                lines.append("| " + " | ".join(["---"] * len(cells)) + " |")
        lines.append("")

    print("\n".join(lines))
    return 0


def read_pdf(path):
    """Extract text from PDF."""
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader

    reader = PdfReader(str(path))
    text_parts = []

    for page_num, page in enumerate(reader.pages, 1):
        text = page.extract_text()
        text_parts.append(f"--- Page {page_num} ---\n{text}")

    print("\n\n".join(text_parts))
    return 0


def read_xlsx(path):
    """Extract data from XLSX as CSV-style output."""
    from openpyxl import load_workbook

    wb = load_workbook(str(path), read_only=True)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        print(f"\n--- Sheet: {sheet_name} ---")

        for row in ws.iter_rows(values_only=True):
            # Filter out completely empty rows
            if any(cell is not None for cell in row):
                row_str = ",".join(str(cell) if cell is not None else "" for cell in row)
                print(row_str)

    return 0


def cmd_write(output_file, input_file=None):
    """Create DOCX from markdown content."""
    from docx import Document

    # Read markdown content
    if input_file:
        content = Path(input_file).read_text(encoding="utf-8")
    else:
        # Read from stdin
        content = sys.stdin.read()

    doc = Document()
    lines = content.split("\n")

    for line in lines:
        line = line.rstrip()

        if not line:
            continue

        # Headings
        if line.startswith("# "):
            doc.add_heading(line[2:], level=1)
        elif line.startswith("## "):
            doc.add_heading(line[3:], level=2)
        elif line.startswith("### "):
            doc.add_heading(line[4:], level=3)
        elif line.startswith("#### "):
            doc.add_heading(line[5:], level=4)
        elif line.startswith("##### "):
            doc.add_heading(line[6:], level=5)
        elif line.startswith("###### "):
            doc.add_heading(line[7:], level=6)
        # Lists
        elif line.startswith("- ") or line.startswith("* "):
            doc.add_paragraph(line[2:], style="List Bullet")
        elif line[0:3].rstrip().isdigit() and ". " in line[:5]:
            # Ordered list
            doc.add_paragraph(line.split(". ", 1)[1], style="List Number")
        else:
            # Regular paragraph
            doc.add_paragraph(line)

    doc.save(output_file)
    print(f"✅ Created: {output_file}")
    return 0


def cmd_convert(input_file, output_file):
    """Convert between document formats."""
    in_path = Path(input_file)
    out_path = Path(output_file)

    if not in_path.exists():
        print(f"❌ File not found: {input_file}", file=sys.stderr)
        return 1

    in_ext = in_path.suffix.lower()
    out_ext = out_path.suffix.lower()

    try:
        # XLSX → CSV
        if in_ext in [".xlsx", ".xls"] and out_ext == ".csv":
            return convert_xlsx_to_csv(in_path, out_path)

        # DOCX → TXT
        elif in_ext == ".docx" and out_ext == ".txt":
            return convert_docx_to_txt(in_path, out_path)

        # PDF → TXT
        elif in_ext == ".pdf" and out_ext == ".txt":
            return convert_pdf_to_txt(in_path, out_path)

        # DOCX → PDF (requires LibreOffice)
        elif in_ext == ".docx" and out_ext == ".pdf":
            print("⚠️  DOCX → PDF requires LibreOffice or unoconv", file=sys.stderr)
            print("   Install: apt-get install libreoffice-writer", file=sys.stderr)
            print(f"   Then run: libreoffice --headless --convert-to pdf {input_file}", file=sys.stderr)
            return 1

        else:
            print(f"❌ Unsupported conversion: {in_ext} → {out_ext}", file=sys.stderr)
            print("   Supported: xlsx→csv, docx→txt, pdf→txt", file=sys.stderr)
            return 1

    except Exception as e:
        print(f"❌ Conversion failed: {e}", file=sys.stderr)
        return 1


def convert_xlsx_to_csv(in_path, out_path):
    """Convert XLSX to CSV (first sheet only)."""
    from openpyxl import load_workbook
    import csv

    wb = load_workbook(str(in_path), read_only=True)
    ws = wb.active  # First sheet

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        for row in ws.iter_rows(values_only=True):
            writer.writerow(row)

    print(f"✅ Converted: {in_path} → {out_path}")
    return 0


def convert_docx_to_txt(in_path, out_path):
    """Convert DOCX to plain text."""
    from docx import Document

    doc = Document(str(in_path))
    text = "\n".join(para.text for para in doc.paragraphs)

    out_path.write_text(text, encoding="utf-8")
    print(f"✅ Converted: {in_path} → {out_path}")
    return 0


def convert_pdf_to_txt(in_path, out_path):
    """Convert PDF to plain text."""
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader

    reader = PdfReader(str(in_path))
    text_parts = [page.extract_text() for page in reader.pages]

    out_path.write_text("\n\n".join(text_parts), encoding="utf-8")
    print(f"✅ Converted: {in_path} → {out_path}")
    return 0


def cmd_template(template_file, data_file):
    """Fill DOCX template with JSON data."""
    from docx import Document

    template_path = Path(template_file)
    data_path = Path(data_file)

    if not template_path.exists():
        print(f"❌ Template not found: {template_file}", file=sys.stderr)
        return 1

    if not data_path.exists():
        print(f"❌ Data file not found: {data_file}", file=sys.stderr)
        return 1

    # Load data
    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON in {data_file}: {e}", file=sys.stderr)
        return 1

    # Load template
    doc = Document(str(template_path))

    # Replace placeholders in paragraphs
    for para in doc.paragraphs:
        for key, value in data.items():
            placeholder = f"{{{{{key}}}}}"
            if placeholder in para.text:
                para.text = para.text.replace(placeholder, str(value))

    # Replace placeholders in tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for key, value in data.items():
                    placeholder = f"{{{{{key}}}}}"
                    if placeholder in cell.text:
                        cell.text = cell.text.replace(placeholder, str(value))

    # Generate output filename
    output_file = template_path.stem + f"-{data.get('id', 'filled')}.docx"
    doc.save(output_file)

    print(f"✅ Generated: {output_file}")
    return 0


def cmd_help():
    """Show usage information."""
    print("""
Document Processing Skill

Usage:
  python docx.py read <file>              # Extract content from DOCX/PDF/XLSX
  python docx.py write <output> [--input <md-file>]  # Create DOCX from markdown
  python docx.py convert <input> <output> # Convert between formats
  python docx.py template <template> <data.json>  # Fill template

Examples:
  python docx.py read contract.docx
  python docx.py write report.docx --input notes.md
  python docx.py convert data.xlsx data.csv
  python docx.py template invoice.docx customer.json

Supported formats:
  Read: .docx, .pdf, .xlsx
  Write: .docx
  Convert: xlsx→csv, docx→txt, pdf→txt
""")
    return 0


def main():
    if len(sys.argv) < 2:
        cmd_help()
        return 1

    # Check dependencies on first run
    if not check_dependencies():
        return 1

    command = sys.argv[1]

    if command == "help":
        return cmd_help()

    elif command == "read":
        if len(sys.argv) < 3:
            print("❌ Usage: docx.py read <file>", file=sys.stderr)
            return 1
        return cmd_read(sys.argv[2])

    elif command == "write":
        if len(sys.argv) < 3:
            print("❌ Usage: docx.py write <output> [--input <file>]", file=sys.stderr)
            return 1
        output = sys.argv[2]
        input_file = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--input" else None
        return cmd_write(output, input_file)

    elif command == "convert":
        if len(sys.argv) < 4:
            print("❌ Usage: docx.py convert <input> <output>", file=sys.stderr)
            return 1
        return cmd_convert(sys.argv[2], sys.argv[3])

    elif command == "template":
        if len(sys.argv) < 4:
            print("❌ Usage: docx.py template <template> <data.json>", file=sys.stderr)
            return 1
        return cmd_template(sys.argv[2], sys.argv[3])

    else:
        print(f"❌ Unknown command: {command}", file=sys.stderr)
        cmd_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
