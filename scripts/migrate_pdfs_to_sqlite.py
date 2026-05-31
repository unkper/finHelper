#!/usr/bin/env python3
"""将磁盘上的财报 PDF（pdf_path）一次性导入 financial_reports.pdf_blob。"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app
from config import Config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import existing financial report PDF files into SQLite BLOB column",
    )
    parser.add_argument(
        "--delete-files",
        action="store_true",
        help="Remove disk PDF files after successful import",
    )
    args = parser.parse_args()

    app = create_app(Config())
    imported = 0
    missing = 0
    already = 0

    with app.app_context():
        from app.database import get_db
        from app.services.financial_reports import save_report_pdf_blob

        db = get_db()
        rows = db.execute(
            """
            SELECT id, pdf_path, pdf_blob IS NOT NULL AS has_blob
            FROM financial_reports
            WHERE pdf_path IS NOT NULL AND pdf_path != ''
            """
        ).fetchall()

        for row in rows:
            report_id = int(row["id"])
            if row["has_blob"]:
                already += 1
                continue
            path = Path(row["pdf_path"] or "")
            if not path.is_file():
                missing += 1
                print(f"[missing] report {report_id}: {path}")
                continue
            data = path.read_bytes()
            if not data[:4] == b"%PDF":
                print(f"[skip] report {report_id}: not a PDF ({path})")
                missing += 1
                continue
            save_report_pdf_blob(report_id, data)
            imported += 1
            print(f"[ok] report {report_id}: {len(data)} bytes from {path}")
            if args.delete_files:
                try:
                    path.unlink()
                    print(f"     deleted {path}")
                except OSError as exc:
                    print(f"     warn: could not delete {path}: {exc}")

    print(
        f"Done: imported={imported}, already_in_db={already}, "
        f"missing_or_invalid={missing}",
    )
    return 0 if missing == 0 or imported > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
