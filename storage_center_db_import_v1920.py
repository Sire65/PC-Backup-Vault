from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import psycopg
from psycopg import sql
from tkinter import filedialog, messagebox, simpledialog


def apply_storage_center_db_import_v1920(WindowClass):
    """Bind DB imports to the exact database node selected in the 1.9.20 tree."""
    if getattr(WindowClass, "_storage_center_db_import_v1920", False):
        return
    WindowClass._storage_center_db_import_v1920 = True

    def db_import(self):
        row = self._relation_selected()
        if not row:
            messagebox.showinfo("Import", "Bitte genau eine Zieltabelle auswählen.", parent=self)
            return
        database = str(row.get("database") or "")
        path = filedialog.askopenfilename(parent=self, title="CSV/JSON importieren", filetypes=[("CSV/JSON","*.csv *.json"),("CSV","*.csv"),("JSON","*.json")])
        if not path:
            return
        target_text = f"{database} · {row['schema']}.{row['table']}"
        typed = simpledialog.askstring(
            "Datenbank-Import bestätigen",
            f"Import fügt Datensätze in {target_text} ein.\nBestehende Datensätze werden nicht automatisch gelöscht.\n\nZum Fortfahren exakt DATENBANK eingeben:",
            parent=self,
        )
        if str(typed or "").strip().upper() != "DATENBANK":
            return
        if not messagebox.askyesno("Import starten", f"Datei wirklich in {target_text} importieren?\n\n{path}", parent=self, default="no"):
            return

        def worker(report):
            p = Path(path)
            if p.suffix.lower() == ".json":
                raw = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(raw, list) or not all(isinstance(x, dict) for x in raw):
                    raise ValueError("JSON muss eine Liste aus Objekten sein.")
                records = raw
                columns = list(records[0].keys()) if records else []
            else:
                text = p.read_text(encoding="utf-8-sig")
                sample = text[:4096]
                delim = ";" if sample.count(";") >= sample.count(",") else ","
                reader = csv.DictReader(io.StringIO(text), delimiter=delim)
                columns = list(reader.fieldnames or [])
                records = list(reader)
            if not columns:
                raise ValueError("Keine Spaltenüberschriften gefunden.")

            with psycopg.connect(self._dsn_for_database(database), connect_timeout=10) as conn:
                rows = conn.execute(
                    """SELECT column_name FROM information_schema.columns
                       WHERE table_schema=%s AND table_name=%s""",
                    (row["schema"], row["table"]),
                ).fetchall()
                known = {str(x[0]) for x in rows}
                unknown = [c for c in columns if c not in known]
                if unknown:
                    raise ValueError("Unbekannte Zielspalten: " + ", ".join(unknown))
                stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                    sql.Identifier(row["schema"]),
                    sql.Identifier(row["table"]),
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    sql.SQL(",").join(sql.Placeholder() for _ in columns),
                )
                vals = [tuple(None if rec.get(c) == "" else rec.get(c) for c in columns) for rec in records]
                for start in range(0, len(vals), 250):
                    batch = vals[start:start+250]
                    conn.executemany(stmt, batch)
                    report(phase="Import läuft", files_done=min(start+len(batch), len(vals)), files_total=len(vals), current_file=target_text)
                conn.commit()
            report(phase="Import abgeschlossen", files_done=len(records), files_total=len(records), current_file=target_text)

        self._run("Datenbank Import", worker, f"Import in {target_text} abgeschlossen", refresh=False)

    WindowClass._db_import = db_import
