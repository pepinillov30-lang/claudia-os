---
name: claudia-finanzas
description: "Análisis de gastos familiares: importa extractos bancarios, categoriza movimientos con reglas, enriquece con detalle de merchants, y genera dashboards."
scope: core
user-invocable: true
argument-hint: "import <file> | categorizar | enrich <merchant> | dashboard | regenerar | rules | status"
---

# Finanzas — Análisis inteligente de gastos

Importa extractos bancarios (CSV), categoriza automáticamente cada movimiento, enriquece con detalle de merchants (Amazon, etc.), y genera dashboards visuales.

> **Personalización:** antes de ejecutar, lee `user/behavior.md` en este directorio. Si tiene contenido, aplícalo como ajustes — en caso de conflicto con lo definido aquí, prevalece lo del usuario.

## First-run: bootstrap automático

Al ejecutar cualquier comando `/claudia-finanzas`, comprobar si existe `user/workspaces/claudia-finanzas/rules.yaml`.

**Si NO existe** (primer uso):
1. Crear `user/workspaces/claudia-finanzas/` con estructura completa:
   ```
   user/workspaces/claudia-finanzas/
   ├── rules.yaml            ← copiado de templates/rules_template.yaml
   ├── CLAUDE.md             ← copiado de templates/workspace.md
   ├── data/extractos/
   ├── data/enrichments/
   └── dashboard/
       └── index.html        ← copiado de templates/dashboard.html
   ```
2. Mensaje de bienvenida:
   ```
   Workspace de finanzas creado. Estructura lista.

   Para empezar:
   1. Pega un extracto bancario CSV aquí o ejecuta /claudia-finanzas import <ruta_al_csv>
   2. Ejecuta /claudia-finanzas categorizar para clasificar movimientos

   Las reglas de categorización están en user/workspaces/claudia-finanzas/rules.yaml.
   Puedes editarlas manualmente o dejar que se actualicen durante la categorización.
   ```
3. No pedir entrevista ni configuración. Sin preguntas. Bootstrap silencioso.

**Si SÍ existe** → ejecutar comando normal.

## Workspace y formato canónico

### Directorio de trabajo

```
user/workspaces/claudia-finanzas/
├── rules.yaml              ← reglas de categorización
├── CLAUDE.md
├── data/
│   ├── extractos/          ← CSVs normalizados (un fichero por periodo: 2024.csv, 2025.csv)
│   └── enrichments/        ← desglose de merchants (amazon_2026.csv, etc.)
└── dashboard/
    ├── index.html          ← dashboard HTML
    └── data.json           ← datos generados por pipeline
```

### Formato CSV canónico

```csv
fecha,concepto,importe,saldo,categoria,movimiento,observaciones
2026-01-03,Mercadona 1234,-67.82,5432.10,alimentacion/supermercado,Pago con tarjeta,4940XXXX MERCADONA
```

- `fecha`: YYYY-MM-DD
- `concepto`: nombre del merchant o descripción
- `importe`: positivo = ingreso, negativo = gasto
- `saldo`: saldo tras el movimiento
- `categoria`: clave de rules.yaml (formato `main/sub`, e.g. `restaurantes/cafes_desayunos`)
- `movimiento`: tipo de movimiento del banco (pago con tarjeta, transferencia, etc.)
- `observaciones`: datos adicionales del banco (número de tarjeta, referencia, etc.)

## Pipeline Python

Los scripts están en `.claude/skills/claudia-finanzas/pipeline/`.

**Invocación:**
```bash
python3 .claude/skills/claudia-finanzas/pipeline/categorize.py user/workspaces/claudia-finanzas
python3 .claude/skills/claudia-finanzas/pipeline/generate.py user/workspaces/claudia-finanzas
python3 .claude/skills/claudia-finanzas/pipeline/insights.py user/workspaces/claudia-finanzas
```

- `categorize.py` — aplica rules.yaml + enrichments a CSVs, output JSON con {matched, uncategorized, total, updated}
- `generate.py` — lee CSVs categorizados → genera data.json para dashboard
- `insights.py` — analiza data.json → añade campos insights y alerts

El pipeline completo es: categorize → generate → insights.

## Comandos

### `/claudia-finanzas import <file>`

Importa un extracto y lo normaliza al CSV canónico.

**Flujo:**
1. Detectar formato con parsers de `.claude/skills/claudia-finanzas/parsers/`
2. Normalizar a CSV canónico con las 7 columnas
3. Dedup: si ya existen datos para el mismo periodo, mergear sin duplicar (fecha+concepto+importe)
4. Guardar en `data/extractos/{año}.csv` (un fichero por año natural)
5. Ejecutar pipeline completo: categorize → generate → insights
6. Mostrar resumen: X movimientos importados, Y categorizados, Z pendientes

### `/claudia-finanzas categorizar`

Categorización asistida interactiva para movimientos sin categoría.

**Flujo:**
1. Ejecutar `categorize.py` para aplicar reglas automáticas
2. Leer CSVs y recoger movimientos con `categoria` vacía
3. Agrupar por concepto normalizado (lowercase, trim)
4. Ordenar por importe acumulado descendente (absoluto)
5. Presentar con referencias numéricas:
   ```
   Movimientos sin categoría (47 en total, 12 conceptos únicos):

   #1   GIMNASIO MCFIT         3 mov ·  89,97 €
   #2   BAR EL RINCÓN          7 mov · 124,50 €
   #3   PEPE FARMACIA          2 mov ·  23,40 €
   ...
   ```
6. El usuario responde con asignaciones: "1 salud/gimnasio, 2 restaurantes, 3 salud/farmacia"
   - Formatos válidos: "1 salud/gimnasio" | "1-3 restaurantes" (rango) | "1,2,5 compras"
7. Por cada asignación:
   a. Actualizar `categoria` en los CSVs para todos los movimientos del concepto
   b. Añadir el pattern al `rules.yaml` en la categoría correspondiente
8. Si quedan pendientes, ofrecer otra ronda
9. Al terminar: ejecutar pipeline generate → insights
10. Mostrar resumen: X categorizados, Y pendientes, sugerir regenerar dashboard

**Importante:** al añadir patterns a rules.yaml, usar el concepto normalizado en minúsculas. Insertar en la categoría correcta respetando la estructura YAML.

### `/claudia-finanzas enrich <merchant>`

Enriquece movimientos de un merchant con detalle de pedidos.

**Flujo:**
1. Pedir al usuario el detalle (CSV exportado o texto del historial)
2. Parsear: fecha_pedido, importe, items, subcategoría
3. Cruzar con extracto por importe exacto + fecha ± 3 días
4. Las subcategorías DEBEN usar claves de rules.yaml (e.g. `ninos/ropa_calzado`, NO `niños/ropa`)
5. Guardar en `data/enrichments/{merchant}_{año}.csv`:
   ```csv
   fecha_pedido,fecha_extracto,importe,subcategoria,items,order_num
   ```
6. Ejecutar pipeline completo

### `/claudia-finanzas dashboard`

Regenera dashboard completo.

**Flujo:**
1. Ejecutar pipeline: categorize → generate → insights
2. Si el servidor HTTP no está corriendo, lanzarlo:
   ```bash
   cd user/workspaces/claudia-finanzas/dashboard && python3 -m http.server 8090 --bind 0.0.0.0 &
   ```
3. Informar la URL de acceso (e.g. `http://localhost:8090`)

### `/claudia-finanzas regenerar`

Alias rápido para regenerar data.json + insights sin categorizar.

**Flujo:**
1. Ejecutar generate.py + insights.py
2. Mostrar resumen

### `/claudia-finanzas rules`

Muestra estadísticas de rules.yaml: categorías, patterns totales, categorías sin patterns.

### `/claudia-finanzas status`

Resumen rápido: periodos importados, movimientos totales, % categorizados, ahorro acumulado.

## Categorización: lógica de matching

El categorizador busca patterns en 3 columnas (concepto + movimiento + observaciones).
Case-insensitive, contains match. Pattern más largo matchea primero.

Orden de prioridad:
1. **Enrichments** — si hay match fecha±3d + importe exacto en enrichments/, usa esa subcategoría
2. **Rules.yaml** — patterns por contains en las 3 columnas
3. **Amount threshold** — `restaurantes/cafes_desayunos` con threshold -20: si |importe| ≤ 20, asigna cafes_desayunos; si > 20, asigna restaurante

Flags especiales en rules.yaml:
- `is_saving: true` → categoría de ahorro (excluida del gasto)
- `is_neutral: true` → categoría neutra (traspasos internos, excluida)
- `is_income: true` → ingresos (excluidos del gasto)

## data.json: contrato con dashboard

```json
{
  "years": ["2024", "2025", "2026"],
  "summary": {"2026": {"ingresos": 218.04, "movimientos": 527, "sin_categoria": 36}},
  "cat_totals": {"2026": {"hipoteca": 3878.38, "alimentacion/supermercado": 3680.73, ...}},
  "monthly_totals": {"2026": {"1": 5432.10, "2": 4891.30, ...}},
  "monthly_by_cat": {"2026": {"1": {"alimentacion": 1246.07, ...}, ...}},
  "top_merchants": {"2026": [["Mercadona", 3680.73], ...]},
  "cat_labels": {"alimentacion": "Alimentación", "suministros/luz": "Suministros / Luz", ...},
  "patterns_map": {"hipoteca": ["pattern1", "pattern2"], ...},
  "concepts_by_cat": {"2026": {"hipoteca": [["Concepto 1", 4, -3772.20], ...]}},
  "insights": [{"type": "interanual", "label": "📈 Vehículo", "text": "...", "direction": "up"}],
  "alerts": [{"icon": "⚠", "text": "..."}],
  "generated_at": "2026-05-22 16:26"
}
```

Claves mensuales: `"1"`, `"2"`, ..., `"12"` (string, NO `"2026-01"`).
Conceptos: `[nombre, count, total]` tuples. Total es negativo para gastos.
Top merchants: `[[nombre, importe_abs], ...]` arrays.

## Parsers de banco

Los parsers viven en `parsers/` y convierten formatos específicos al CSV canónico.

Cada parser es un módulo Python con:
- `detect(header_line: str) -> bool`
- `parse(content: str) -> list[dict]` → retorna `{fecha, concepto, importe, saldo}`

## Notas de diseño

- **Privacidad:** los datos financieros nunca salen del sistema local
- **Idempotencia:** importar el mismo extracto no duplica (dedup por fecha+concepto+importe)
- **Separación framework/usuario:** templates y pipeline en la skill (actualizable), datos y rules en el workspace del usuario (protegido)
