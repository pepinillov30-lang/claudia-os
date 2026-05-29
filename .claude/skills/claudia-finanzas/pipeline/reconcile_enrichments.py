#!/usr/bin/env python3
"""
Reconcilia enrichments provisionales tras importar un nuevo extracto.

Para cada CSV de enrichments, re-ejecuta el matching contra los extractos actuales.
Los provisionales que ahora caigan dentro del rango del extracto se resuelven como
matched o unmatched.

Uso:
    python3 reconcile_enrichments.py <workspace_path>

Output: JSON a stdout con transiciones y lista de unmatched para revisión del usuario.
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

from match_enrichments import FIELDNAMES, find_match, load_extractos


def reconcile(workspace_path):
    extractos_dir = os.path.join(workspace_path, "data", "extractos")
    enrichments_dir = os.path.join(workspace_path, "data", "enrichments")

    if not os.path.isdir(enrichments_dir):
        print(json.dumps({"transitions": [], "unmatched_review": [], "files_processed": 0}))
        return

    movements, max_extracto_date = load_extractos(extractos_dir)

    transitions = []
    unmatched_review = []
    files_processed = 0

    for fname in sorted(os.listdir(enrichments_dir)):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(enrichments_dir, fname)

        rows = []
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        if not any(r.get("status", "").strip() == "provisional" for r in rows):
            continue

        files_processed += 1

        groups = defaultdict(list)
        for i, row in enumerate(rows):
            fecha = row.get("fecha_pedido", "").strip()
            importe = row.get("importe_total", "").strip()
            key = (fecha, importe)
            groups[key].append(i)

        changed = False
        for (fecha_str, importe_str), indices in groups.items():
            first_status = rows[indices[0]].get("status", "").strip()
            if first_status != "provisional":
                continue

            try:
                fecha_pedido = datetime.strptime(fecha_str, "%Y-%m-%d")
                importe_total = float(importe_str.replace(",", "."))
            except (ValueError, TypeError):
                continue

            fecha_extracto = find_match(fecha_pedido, importe_total, movements)

            if fecha_extracto:
                new_status = "matched"
            elif max_extracto_date and fecha_pedido <= max_extracto_date:
                new_status = "unmatched"
            else:
                continue

            for idx in indices:
                rows[idx]["status"] = new_status
                if fecha_extracto:
                    rows[idx]["fecha_extracto"] = fecha_extracto
                changed = True

            items = [rows[idx].get("item", "").strip() for idx in indices]
            transition = {
                "source": fname,
                "fecha_pedido": fecha_str,
                "importe_total": importe_str,
                "items": items,
                "old_status": "provisional",
                "new_status": new_status,
            }
            transitions.append(transition)

            if new_status == "unmatched":
                unmatched_review.append(transition)

        if changed:
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
                writer.writerows(rows)

    result = {
        "files_processed": files_processed,
        "transitions": transitions,
        "newly_matched": sum(1 for t in transitions if t["new_status"] == "matched"),
        "newly_unmatched": sum(1 for t in transitions if t["new_status"] == "unmatched"),
        "unmatched_review": unmatched_review,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <workspace_path>")
        sys.exit(1)
    reconcile(sys.argv[1])
