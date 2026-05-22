#!/usr/bin/env python3
"""
Categoriza movimientos de extractos bancarios usando rules.yaml.

Busca patrones en concepto + movimiento + observaciones (3 columnas).
Aplica enrichments como override cuando hay match fecha±3d + importe exacto.
Respeta amount_threshold para reclasificaciones automáticas.

Uso:
    python3 categorize.py <workspace_path>

Output: resumen JSON a stdout {matched, uncategorized, total, updated}
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta

import yaml


def load_rules(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    categories = data.get("categories", {})
    rules = []
    for cat_key, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        patterns = cat_data.get("patterns", [])
        if not patterns:
            continue
        threshold = cat_data.get("amount_threshold")
        redirect_cat = None
        if threshold is not None:
            main = cat_key.split("/")[0] if "/" in cat_key else cat_key
            for other_key, other_data in categories.items():
                if other_key != cat_key and other_key.startswith(main + "/"):
                    if isinstance(other_data, dict) and other_data.get("amount_threshold") is not None:
                        continue
                    redirect_cat = other_key
                    break
        for pat in patterns:
            rules.append({
                "pattern": str(pat).lower(),
                "category": cat_key,
                "threshold": threshold,
                "redirect_cat": redirect_cat,
            })
    rules.sort(key=lambda r: -len(r["pattern"]))
    return rules


def load_enrichments(enrichments_dir):
    enrichments = []
    if not os.path.isdir(enrichments_dir):
        return enrichments
    for fname in os.listdir(enrichments_dir):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(enrichments_dir, fname)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                fecha_extracto = row.get("fecha_extracto", "").strip()
                importe_str = row.get("importe", "").strip()
                subcat = row.get("subcategoria", "").strip()
                if not fecha_extracto or not importe_str or not subcat:
                    continue
                try:
                    importe = float(importe_str.replace(",", "."))
                    dt = datetime.strptime(fecha_extracto, "%Y-%m-%d")
                except (ValueError, TypeError):
                    continue
                enrichments.append({
                    "fecha": dt,
                    "importe": importe,
                    "category": subcat,
                })
    return enrichments


def match_enrichment(fecha_str, importe, enrichments, tolerance_days=3):
    try:
        dt = datetime.strptime(fecha_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    for e in enrichments:
        if abs((dt - e["fecha"]).days) <= tolerance_days and abs(importe - e["importe"]) < 0.01:
            return e["category"]
    return None


def categorize_row(concepto, movimiento, observaciones, importe, rules):
    search_text = f"{concepto} {movimiento} {observaciones}".lower()
    for rule in rules:
        if rule["pattern"] in search_text:
            cat = rule["category"]
            if rule["threshold"] is not None and importe < 0:
                if abs(importe) <= abs(rule["threshold"]):
                    return cat
                elif rule["redirect_cat"]:
                    return rule["redirect_cat"]
            return cat
    return None


def process_workspace(workspace_path):
    rules_path = os.path.join(workspace_path, "rules.yaml")
    extractos_dir = os.path.join(workspace_path, "data", "extractos")
    enrichments_dir = os.path.join(workspace_path, "data", "enrichments")

    if not os.path.isfile(rules_path):
        print(json.dumps({"error": "rules.yaml not found", "path": rules_path}))
        sys.exit(1)

    rules = load_rules(rules_path)
    enrichments = load_enrichments(enrichments_dir)

    total = 0
    matched = 0
    uncategorized = 0
    updated = 0

    csv_files = sorted(
        f for f in os.listdir(extractos_dir) if f.endswith(".csv")
    ) if os.path.isdir(extractos_dir) else []

    if not csv_files:
        print(json.dumps({"error": "No CSV files found", "path": extractos_dir}))
        sys.exit(1)

    for fname in csv_files:
        fpath = os.path.join(extractos_dir, fname)
        rows = []
        with open(fpath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                rows.append(row)

        changed = False
        for row in rows:
            total += 1
            fecha = row.get("fecha", "").strip()
            concepto = row.get("concepto", "").strip()
            movimiento = row.get("movimiento", "").strip()
            observaciones = row.get("observaciones", "").strip()
            try:
                importe = float(row.get("importe", "0").replace(",", "."))
            except (ValueError, TypeError):
                importe = 0.0

            existing_cat = row.get("categoria", "").strip()

            enrich_cat = match_enrichment(fecha, importe, enrichments)
            if enrich_cat:
                if existing_cat != enrich_cat:
                    row["categoria"] = enrich_cat
                    changed = True
                    updated += 1
                matched += 1
                continue

            if existing_cat:
                matched += 1
                continue

            new_cat = categorize_row(concepto, movimiento, observaciones, importe, rules)
            if new_cat:
                row["categoria"] = new_cat
                changed = True
                matched += 1
                updated += 1
            else:
                uncategorized += 1

        if changed:
            with open(fpath, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

    result = {
        "total": total,
        "matched": matched,
        "uncategorized": uncategorized,
        "updated": updated,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <workspace_path>")
        sys.exit(1)
    process_workspace(sys.argv[1])
