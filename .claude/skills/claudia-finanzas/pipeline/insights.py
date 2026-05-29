#!/usr/bin/env python3
"""
Genera insights y alertas a partir de data.json existente.

- Comparativa interanual por categoría (>15% cambio → flag)
- Tendencias consecutivas (3+ meses subiendo/bajando)
- Mes anómalo (>1.5x de la media)
- Tasa de ahorro vs periodo anterior

Uso:
    python3 insights.py <workspace_path>

Output: actualiza data.json con campos insights y alerts.
"""

import json
import os
import sys


def main_cat(c):
    return c.split("/")[0] if "/" in c else c


EXCLUDE = {"ahorros", "traspasos_internos", "sin_categoria", "ingresos"}


def generate_insights(data):
    insights = []
    alerts = []
    years = data["years"]

    if len(years) < 2:
        return insights, alerts

    curr_y = years[-1]
    prev_y = years[-2]
    curr_months = len(data["monthly_totals"].get(curr_y, {}))
    prev_months = len(data["monthly_totals"].get(prev_y, {}))

    if curr_months == 0 or prev_months == 0:
        return insights, alerts

    # --- Interanual por categoría principal ---
    curr_cats = {}
    prev_cats = {}
    for c, v in data["cat_totals"].get(curr_y, {}).items():
        m = main_cat(c)
        if m in EXCLUDE:
            continue
        curr_cats[m] = curr_cats.get(m, 0) + v
    for c, v in data["cat_totals"].get(prev_y, {}).items():
        m = main_cat(c)
        if m in EXCLUDE:
            continue
        prev_cats[m] = prev_cats.get(m, 0) + v

    for cat in sorted(set(curr_cats) | set(prev_cats)):
        curr_avg = curr_cats.get(cat, 0) / curr_months
        prev_avg = prev_cats.get(cat, 0) / prev_months
        if prev_avg < 10:
            continue
        delta_pct = (curr_avg - prev_avg) / prev_avg * 100
        if abs(delta_pct) < 15:
            continue
        label = data["cat_labels"].get(cat, cat)
        direction = "up" if delta_pct > 0 else "down"
        sign = "+" if delta_pct > 0 else ""
        insights.append({
            "type": "interanual",
            "label": f"{'📈' if direction == 'up' else '📉'} {label}",
            "text": f"{label}: media mensual {sign}{delta_pct:.0f}% vs {prev_y} ({curr_avg:.0f} €/mes → {prev_avg:.0f} €/mes en {prev_y})",
            "direction": direction,
            "category": cat,
            "delta_pct": round(delta_pct, 1),
        })

    insights.sort(key=lambda i: -abs(i.get("delta_pct", 0)))

    # --- Tendencia consecutiva (3+ meses) ---
    monthly_data = data["monthly_by_cat"].get(curr_y, {})
    months_sorted = sorted(monthly_data.keys(), key=int)
    if len(months_sorted) >= 3:
        cat_monthly = {}
        for m in months_sorted:
            for c, v in monthly_data[m].items():
                mc = main_cat(c)
                if mc in EXCLUDE:
                    continue
                if mc not in cat_monthly:
                    cat_monthly[mc] = {}
                cat_monthly[mc][m] = cat_monthly[mc].get(m, 0) + v

        for cat, monthly in cat_monthly.items():
            vals = [monthly.get(m, 0) for m in months_sorted]
            streak_up = 0
            streak_down = 0
            for i in range(1, len(vals)):
                if vals[i] > vals[i - 1] * 1.05:
                    streak_up += 1
                    streak_down = 0
                elif vals[i] < vals[i - 1] * 0.95:
                    streak_down += 1
                    streak_up = 0
                else:
                    streak_up = 0
                    streak_down = 0
            if streak_up >= 2 or streak_down >= 2:
                label = data["cat_labels"].get(cat, cat)
                direction = "up" if streak_up >= 2 else "down"
                n = max(streak_up, streak_down) + 1
                insights.append({
                    "type": "tendencia",
                    "label": f"{'📈' if direction == 'up' else '📉'} Tendencia",
                    "text": f"{label}: {n} meses consecutivos {'subiendo' if direction == 'up' else 'bajando'} en {curr_y}",
                    "direction": direction,
                    "category": cat,
                })

    # --- Mes anómalo ---
    for m_key in months_sorted:
        m_total = sum(
            v for c, v in monthly_data.get(m_key, {}).items()
            if main_cat(c) not in EXCLUDE
        )
        all_totals = []
        for mk in months_sorted:
            t = sum(
                v for c, v in monthly_data.get(mk, {}).items()
                if main_cat(c) not in EXCLUDE
            )
            all_totals.append(t)
        if len(all_totals) < 3:
            continue
        avg = sum(all_totals) / len(all_totals)
        if avg > 0 and m_total > avg * 1.5:
            month_names = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
                           "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
            m_name = month_names[int(m_key) - 1] if m_key.isdigit() else m_key
            alerts.append({
                "icon": "⚠",
                "text": f"{m_name} {curr_y}: gasto de {m_total:.0f} € — {m_total/avg:.1f}x la media mensual ({avg:.0f} €)",
            })

    # --- Tasa de ahorro ---
    curr_savings = sum(
        v for c, v in data["cat_totals"].get(curr_y, {}).items()
        if main_cat(c) == "ahorros"
    )
    prev_savings = sum(
        v for c, v in data["cat_totals"].get(prev_y, {}).items()
        if main_cat(c) == "ahorros"
    )
    curr_savings_monthly = curr_savings / curr_months if curr_months else 0
    prev_savings_monthly = prev_savings / prev_months if prev_months else 0
    if prev_savings_monthly > 0:
        delta = (curr_savings_monthly - prev_savings_monthly) / prev_savings_monthly * 100
        if abs(delta) > 10:
            direction = "up" if delta > 0 else "down"
            sign = "+" if delta > 0 else ""
            insights.append({
                "type": "ahorro",
                "label": f"{'📈' if direction == 'up' else '📉'} Ahorro",
                "text": f"Tasa de ahorro mensual {sign}{delta:.0f}% vs {prev_y} ({curr_savings_monthly:.0f} €/mes vs {prev_savings_monthly:.0f} €/mes)",
                "direction": direction,
            })

    # --- Alerta: sin categoría ---
    sin_cat = data["summary"].get(curr_y, {}).get("sin_categoria", 0)
    if sin_cat > 20:
        alerts.append({
            "icon": "❓",
            "text": f"{sin_cat} movimientos sin categoría en {curr_y}. Ejecuta /claudia-finanzas categorizar para clasificarlos.",
        })

    # --- Sugerencias de reglas: conceptos repetidos en categorías genéricas ---
    generic_cats = {"sin_categoria", "compras/otros", "ninos/otros", "hogar/otros",
                    "ocio/otros", "salud/otros", "bizums"}
    exclude_cats = {"ingresos", "ingresos/otros", "ingresos/nomina",
                    "ahorros", "traspasos_internos"}
    candidate_concepts = {}
    for y in years:
        for cat, tuples in data.get("concepts_by_cat", {}).get(y, {}).items():
            if cat in exclude_cats or cat.split("/")[0] in {"ingresos", "ahorros", "traspasos_internos"}:
                continue
            if cat not in generic_cats and not cat.endswith("/otros"):
                continue
            for name, count, total in tuples:
                if count < 2:
                    continue
                key = name.lower().strip()
                if key not in candidate_concepts:
                    candidate_concepts[key] = {"name": name, "count": 0, "total": 0.0, "cat": cat}
                candidate_concepts[key]["count"] += count
                candidate_concepts[key]["total"] += total

    rule_suggestions = []
    for key, info in sorted(candidate_concepts.items(), key=lambda x: -x[1]["count"]):
        if info["count"] >= 2:
            rule_suggestions.append({
                "concept": info["name"],
                "count": info["count"],
                "total": round(info["total"], 2),
                "current_cat": info["cat"],
            })
    data["rule_suggestions"] = rule_suggestions[:20]

    return insights, alerts


def process(workspace_path):
    data_path = os.path.join(workspace_path, "dashboard", "data.json")

    if not os.path.isfile(data_path):
        print(f"Error: {data_path} not found. Run generate.py first.")
        sys.exit(1)

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    insights, alerts = generate_insights(data)
    data["insights"] = insights
    data["alerts"] = alerts

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=None)

    print(f"Insights: {len(insights)}, Alerts: {len(alerts)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <workspace_path>")
        sys.exit(1)
    process(sys.argv[1])
