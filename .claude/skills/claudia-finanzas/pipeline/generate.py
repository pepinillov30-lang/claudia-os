#!/usr/bin/env python3
"""
Genera data.json para el dashboard a partir de CSVs categorizados y rules.yaml.

Uso:
    python3 generate.py <workspace_path>

Output: escribe dashboard/data.json
"""

import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

import yaml

CAT_MAIN_LABELS = {
    "hipoteca": "Hipoteca",
    "suministros": "Suministros",
    "alimentacion": "Alimentación",
    "restaurantes": "Restaurantes",
    "compras": "Compras",
    "salud": "Salud",
    "estetica": "Estética",
    "seguros": "Seguros",
    "ninos": "Niños",
    "hogar": "Hogar",
    "vehiculo": "Vehículo",
    "suscripciones": "Suscripciones",
    "ocio": "Ocio",
    "vacaciones": "Vacaciones",
    "mascota": "Mascota",
    "ahorros": "Ahorros",
    "bizums": "Bizums",
    "traspasos_internos": "Traspasos internos",
    "donaciones": "Donaciones",
    "financiero": "Financiero",
    "ingresos": "Ingresos",
}

INCOME_CATS = {"ingresos"}
NEUTRAL_FLAGS = {"is_neutral", "is_income"}


def load_rules(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    categories = data.get("categories", {})
    cat_labels = {}
    patterns_map = {}
    enrichment_patterns_map = {}
    for cat_key, cat_data in categories.items():
        if not isinstance(cat_data, dict):
            continue
        label = cat_data.get("label")
        if label:
            cat_labels[cat_key] = label
        patterns = cat_data.get("patterns", [])
        if patterns:
            patterns_map[cat_key] = [str(p) for p in patterns]
        e_patterns = cat_data.get("enrichment_patterns", [])
        if e_patterns:
            enrichment_patterns_map[cat_key] = [str(p) for p in e_patterns]
    return cat_labels, patterns_map, enrichment_patterns_map


def main_cat(c):
    return c.split("/")[0] if "/" in c else c


def load_enrichment_breakdown(enrichments_dir):
    breakdown = defaultdict(lambda: defaultdict(float))
    items = defaultdict(lambda: defaultdict(list))
    if not os.path.isdir(enrichments_dir):
        return {}, {}
    for fname in os.listdir(enrichments_dir):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(enrichments_dir, fname)
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                status = row.get("status", "matched").strip()
                if status != "matched":
                    continue
                subcat = row.get("subcategoria", "").strip()
                importe_str = row.get("importe_item", row.get("importe", "")).strip()
                fecha = row.get("fecha_extracto", row.get("fecha_pedido", "")).strip()
                if not subcat or not importe_str or len(fecha) < 4:
                    continue
                try:
                    amount = abs(float(importe_str.replace(",", ".")))
                except (ValueError, TypeError):
                    continue
                year = fecha[:4]
                breakdown[year][subcat] += amount
                item_name = row.get("item", "").strip()
                source = row.get("source", "").strip()
                if item_name:
                    items[year][subcat].append([item_name, round(amount, 2), source])
    totals = {}
    for year, cats in breakdown.items():
        totals[year] = {cat: round(total, 2) for cat, total in sorted(cats.items())}
    items_out = {}
    for year, cats in items.items():
        items_out[year] = {cat: lst for cat, lst in sorted(cats.items())}
    return totals, items_out


def generate(workspace_path):
    rules_path = os.path.join(workspace_path, "rules.yaml")
    extractos_dir = os.path.join(workspace_path, "data", "extractos")
    dashboard_dir = os.path.join(workspace_path, "dashboard")

    cat_labels, patterns_map, enrichment_patterns_map = load_rules(rules_path)
    for main, label in CAT_MAIN_LABELS.items():
        if main not in cat_labels:
            cat_labels[main] = label

    csv_files = sorted(
        f for f in os.listdir(extractos_dir) if f.endswith(".csv")
    ) if os.path.isdir(extractos_dir) else []

    all_rows = []
    for fname in csv_files:
        fpath = os.path.join(extractos_dir, fname)
        with open(fpath, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                all_rows.append(row)

    years_set = set()
    for row in all_rows:
        fecha = row.get("fecha", "")
        if len(fecha) >= 4:
            years_set.add(fecha[:4])
    years = sorted(years_set)

    summary = {}
    cat_totals = defaultdict(lambda: defaultdict(float))
    monthly_totals = defaultdict(lambda: defaultdict(float))
    monthly_by_cat = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    concepts_by_cat = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"count": 0, "total": 0.0})))
    top_merchants_data = defaultdict(lambda: defaultdict(float))

    for year in years:
        summary[year] = {"ingresos": 0.0, "movimientos": 0, "sin_categoria": 0}

    for row in all_rows:
        fecha = row.get("fecha", "").strip()
        concepto = row.get("concepto", "").strip()
        categoria = row.get("categoria", "").strip()
        try:
            importe = float(row.get("importe", "0").replace(",", "."))
        except (ValueError, TypeError):
            continue

        if len(fecha) < 7:
            continue
        year = fecha[:4]
        month = str(int(fecha[5:7]))

        if year not in summary:
            continue

        summary[year]["movimientos"] += 1

        if importe > 0:
            summary[year]["ingresos"] += importe

        if not categoria:
            summary[year]["sin_categoria"] += 1
            cat_totals[year]["sin_categoria"] += abs(importe)
            continue

        cat_totals[year][categoria] += abs(importe)
        monthly_totals[year][month] += abs(importe)
        monthly_by_cat[year][month][categoria] += abs(importe)

        if concepto:
            concepts_by_cat[year][categoria][concepto]["count"] += 1
            concepts_by_cat[year][categoria][concepto]["total"] += importe

        if importe < 0 and concepto:
            top_merchants_data[year][concepto] += abs(importe)

    cat_totals_out = {}
    for y in years:
        cat_totals_out[y] = dict(cat_totals[y])

    monthly_totals_out = {}
    for y in years:
        monthly_totals_out[y] = dict(monthly_totals[y])

    monthly_by_cat_out = {}
    for y in years:
        monthly_by_cat_out[y] = {}
        for m, cats in monthly_by_cat[y].items():
            monthly_by_cat_out[y][m] = dict(cats)

    concepts_out = {}
    for y in years:
        concepts_out[y] = {}
        for cat, concepts in concepts_by_cat[y].items():
            tuples = [[name, d["count"], d["total"]] for name, d in concepts.items()]
            tuples.sort(key=lambda t: t[2])
            concepts_out[y][cat] = tuples

    top_merchants_out = {}
    for y in years:
        merchants = sorted(top_merchants_data[y].items(), key=lambda x: -x[1])[:20]
        top_merchants_out[y] = [[name, round(amount, 2)] for name, amount in merchants]

    enrichment_breakdown, enrichment_items = load_enrichment_breakdown(
        os.path.join(workspace_path, "data", "enrichments")
    )

    data = {
        "years": years,
        "summary": summary,
        "cat_totals": cat_totals_out,
        "monthly_totals": monthly_totals_out,
        "monthly_by_cat": monthly_by_cat_out,
        "top_merchants": top_merchants_out,
        "cat_labels": cat_labels,
        "patterns_map": patterns_map,
        "enrichment_patterns_map": enrichment_patterns_map,
        "concepts_by_cat": concepts_out,
        "enrichment_breakdown": enrichment_breakdown,
        "enrichment_items": enrichment_items,
        "insights": [],
        "alerts": [],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    os.makedirs(dashboard_dir, exist_ok=True)
    out_path = os.path.join(dashboard_dir, "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=None)

    print(f"data.json generado: {len(all_rows)} movimientos, {len(years)} años")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <workspace_path>")
        sys.exit(1)
    generate(sys.argv[1])
