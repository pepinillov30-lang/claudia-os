#!/usr/bin/env python3
"""
Cruza enrichments con el extracto bancario por fecha+importe.

Para cada grupo de line items (mismo fecha_pedido + importe_total):
- Si hay match en extracto (fecha ±5d, importe ±0.02) → status=matched
- Si el extracto no cubre la fecha → status=provisional
- Si el extracto cubre la fecha pero no hay match → status=unmatched

Uso:
    python3 match_enrichments.py <workspace_path> <enrichment_csv>

Output: JSON a stdout {matched, provisional, unmatched, groups}
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta


def load_extractos(extractos_dir):
    movements = []
    max_date = None
    if not os.path.isdir(extractos_dir):
        return movements, max_date
    for fname in sorted(os.listdir(extractos_dir)):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(extractos_dir, fname)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fecha = row.get("fecha", "").strip()
                importe_str = row.get("importe", "").strip()
                if not fecha or not importe_str:
                    continue
                try:
                    dt = datetime.strptime(fecha, "%Y-%m-%d")
                    importe = float(importe_str.replace(",", "."))
                except (ValueError, TypeError):
                    continue
                movements.append({"fecha": dt, "importe": importe})
                if max_date is None or dt > max_date:
                    max_date = dt
    return movements, max_date


def find_match(fecha_pedido, importe_total, movements, tolerance_days=5, tolerance_amount=0.02):
    for m in movements:
        if abs((m["fecha"] - fecha_pedido).days) <= tolerance_days and abs(m["importe"] - importe_total) < tolerance_amount:
            return m["fecha"].strftime("%Y-%m-%d")
    return None


FIELDNAMES = [
    "fecha_pedido", "fecha_extracto", "importe_total", "importe_item",
    "subcategoria", "item", "source", "status",
]


def process(workspace_path, enrichment_csv):
    extractos_dir = os.path.join(workspace_path, "data", "extractos")
    movements, max_extracto_date = load_extractos(extractos_dir)

    rows = []
    with open(enrichment_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    groups = defaultdict(list)
    for i, row in enumerate(rows):
        fecha = row.get("fecha_pedido", "").strip()
        importe = row.get("importe_total", "").strip()
        key = (fecha, importe)
        groups[key].append(i)

    matched_count = 0
    provisional_count = 0
    unmatched_count = 0
    changed = False

    for (fecha_str, importe_str), indices in groups.items():
        try:
            fecha_pedido = datetime.strptime(fecha_str, "%Y-%m-%d")
            importe_total = float(importe_str.replace(",", "."))
        except (ValueError, TypeError):
            continue

        fecha_extracto = find_match(fecha_pedido, importe_total, movements)

        if fecha_extracto:
            status = "matched"
            matched_count += len(indices)
        elif max_extracto_date is None or fecha_pedido > max_extracto_date:
            status = "provisional"
            fecha_extracto = ""
            provisional_count += len(indices)
        else:
            status = "unmatched"
            fecha_extracto = ""
            unmatched_count += len(indices)

        for idx in indices:
            if rows[idx].get("status") != status or rows[idx].get("fecha_extracto", "") != fecha_extracto:
                rows[idx]["status"] = status
                if fecha_extracto:
                    rows[idx]["fecha_extracto"] = fecha_extracto
                changed = True

    if changed:
        with open(enrichment_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

    print(json.dumps({
        "matched": matched_count,
        "provisional": provisional_count,
        "unmatched": unmatched_count,
        "groups": len(groups),
    }))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <workspace_path> <enrichment_csv>")
        sys.exit(1)
    process(sys.argv[1], sys.argv[2])
