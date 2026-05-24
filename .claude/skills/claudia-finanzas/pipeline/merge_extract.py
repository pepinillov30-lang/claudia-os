#!/usr/bin/env python3
"""
Mergea un extracto normalizado (CSV canónico) con los extractos existentes.

Dedup por tupla (fecha, concepto, importe). Agrupa por año.
No toca categorías existentes — solo añade filas nuevas.

Uso:
    python3 merge_extract.py <workspace_path> <new_csv_path>

Output: resumen JSON a stdout {new, duplicates, total, years_affected}
"""

import csv
import json
import os
import sys
from collections import defaultdict

FIELDNAMES = ["fecha", "concepto", "importe", "saldo", "categoria", "movimiento", "observaciones"]


def dedup_key(row):
    fecha = row.get("fecha", "").strip()
    concepto = row.get("concepto", "").strip().lower()
    try:
        importe = f"{float(row.get('importe', '0').replace(',', '.')):.2f}"
    except (ValueError, TypeError):
        importe = "0.00"
    return (fecha, concepto, importe)


def load_csv(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def write_csv(path, rows):
    rows.sort(key=lambda r: r.get("fecha", ""))
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def merge(workspace_path, new_csv_path):
    extractos_dir = os.path.join(workspace_path, "data", "extractos")
    os.makedirs(extractos_dir, exist_ok=True)

    new_rows = load_csv(new_csv_path)
    if not new_rows:
        print(json.dumps({"error": "No rows in new CSV", "path": new_csv_path}))
        sys.exit(1)

    by_year = defaultdict(list)
    for row in new_rows:
        year = row.get("fecha", "")[:4]
        if len(year) == 4:
            by_year[year].append(row)

    total_new = 0
    total_dups = 0
    years_affected = []

    for year, rows in sorted(by_year.items()):
        existing_path = os.path.join(extractos_dir, f"{year}.csv")
        existing_rows = load_csv(existing_path)
        existing_keys = {dedup_key(r) for r in existing_rows}

        new_count = 0
        dup_count = 0
        for row in rows:
            clean = {f: row.get(f, "") for f in FIELDNAMES}
            key = dedup_key(clean)
            if key in existing_keys:
                dup_count += 1
            else:
                existing_rows.append(clean)
                existing_keys.add(key)
                new_count += 1

        if new_count > 0:
            write_csv(existing_path, existing_rows)
            years_affected.append(year)

        total_new += new_count
        total_dups += dup_count

    result = {
        "new": total_new,
        "duplicates": total_dups,
        "total": total_new + total_dups,
        "years_affected": years_affected,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <workspace_path> <new_csv_path>")
        sys.exit(1)
    merge(sys.argv[1], sys.argv[2])
