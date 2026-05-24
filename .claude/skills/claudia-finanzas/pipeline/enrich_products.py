#!/usr/bin/env python3
"""
Categoriza productos de enrichments usando enrichment_rules.yaml.

Para cada fila sin subcategoria, busca match del campo 'item' contra patterns.
Case-insensitive contains, longest pattern wins (misma lógica que categorize.py).

Uso:
    python3 enrich_products.py <workspace_path> <enrichment_csv>

Output: JSON a stdout {total, matched, unmatched, unmatched_items}
"""

import csv
import json
import os
import sys

import yaml

FIELDNAMES = [
    "fecha_pedido", "fecha_extracto", "importe_total", "importe_item",
    "subcategoria", "item", "source", "status",
]


def load_rules(path):
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    categories = data.get("categories") or {}
    rules = []
    for cat_key, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        patterns = cat_data.get("enrichment_patterns", [])
        if not patterns:
            continue
        for pat in patterns:
            rules.append({"pattern": str(pat).lower(), "category": cat_key})
    rules.sort(key=lambda r: -len(r["pattern"]))
    return rules


def match_product(item_text, rules):
    text = item_text.lower()
    for rule in rules:
        if rule["pattern"] in text:
            return rule["category"]
    return None


def process(workspace_path, enrichment_csv):
    rules_path = os.path.join(workspace_path, "rules.yaml")
    rules = load_rules(rules_path)

    rows = []
    with open(enrichment_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    total = len(rows)
    matched = 0
    unmatched = 0
    unmatched_items = []
    changed = False

    for row in rows:
        existing = row.get("subcategoria", "").strip()
        if existing:
            matched += 1
            continue
        item = row.get("item", "").strip()
        if not item:
            unmatched += 1
            continue
        cat = match_product(item, rules)
        if cat:
            row["subcategoria"] = cat
            matched += 1
            changed = True
        else:
            unmatched += 1
            unmatched_items.append(item)

    if changed:
        with open(enrichment_csv, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)

    print(json.dumps({
        "total": total,
        "matched": matched,
        "unmatched": unmatched,
        "unmatched_items": unmatched_items,
    }))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <workspace_path> <enrichment_csv>")
        sys.exit(1)
    process(sys.argv[1], sys.argv[2])
