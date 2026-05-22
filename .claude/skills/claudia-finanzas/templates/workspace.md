# Workspace: Finanzas

Análisis de gastos familiares. Extractos bancarios categorizados y enriquecidos con detalle de merchants.

## Estructura

```
data/
├── extractos/       ← CSVs normalizados (un fichero por periodo: 2024.csv, 2025.csv, etc.)
└── enrichments/     ← Desglose de merchants (amazon_2026.csv, etc.)
rules.yaml           ← Reglas de categorización (editable por el usuario)
dashboard/           ← Output visual generado
```

## Skill asociada

La skill `/claudia-finanzas` (en `.claude/skills/claudia-finanzas/`) gestiona todo el ciclo:
import → categorizar → enrich → dashboard.

## Formato CSV canónico

```
fecha,concepto,importe,saldo,categoria,movimiento,observaciones
```

- `fecha`: YYYY-MM-DD
- `concepto`: nombre del merchant o descripción del movimiento
- `importe`: positivo = ingreso, negativo = gasto
- `saldo`: saldo tras el movimiento
- `categoria`: de rules.yaml (formato `main/sub`, e.g. `restaurantes/cafes_desayunos`)
- `movimiento`: tipo de movimiento del banco (pago con tarjeta, transferencia, etc.)
- `observaciones`: datos adicionales del banco (número de tarjeta, referencia, etc.)

## Comandos útiles

- `/claudia-finanzas import <fichero>` — importar extracto bancario
- `/claudia-finanzas categorizar` — categorizar movimientos pendientes (interactivo)
- `/claudia-finanzas dashboard` — regenerar dashboard visual
- `/claudia-finanzas status` — resumen rápido del estado
