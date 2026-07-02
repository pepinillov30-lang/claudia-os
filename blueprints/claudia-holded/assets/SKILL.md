---
name: claudia-holded
description: "Automatiza facturas de compra de proveedores en Holded: lee correos etiquetados en Gmail, extrae los datos del PDF, comprueba duplicados y crea la compra en Holded (con PDF adjunto). Ante cualquier duda no sube y lo pregunta en el chat. Usar cuando el usuario pida procesar/subir facturas de proveedor."
scope: user
user-invocable: true
argument-hint: "[procesar|pendientes|resolver]"
---

# Holded — Facturas de compra (proveedores)

Pipeline: **Gmail etiquetado → extraer PDF → dedup → crear compra en Holded + adjuntar PDF → marcar procesado**. Todo lo dudoso se deja sin subir y se notifica.

> **Personalización:** lee `user/behavior.md` en este directorio y aplícalo como ajustes; en conflicto, prevalece lo del usuario.

## Configuración (nada personal vive en la skill)

- **Config:** `user/config/holded.json` (copiar de `config.example.json`). Define cuentas de Gmail, etiquetas, canal de notificación, tolerancias y overrides por proveedor.
- **API key:** `user/credentials/.env` → `HOLDED_API_KEY` (token `pat_` de la API v2; Holded → Configuración → Desarrolladores).
- **Cuentas Gmail:** se autorizan con la skill `claudia-gmail` (`auth.py <alias>`); esta skill reutiliza esos tokens.
- Si falta config o credenciales, **para y pídeselas al usuario**. No inventes valores.

## Helpers (parte determinista)

Ejecuta siempre con el intérprete que tenga las libs de Google (el venv de `claudia-gmail`):

```bash
PY=.claude/skills/claudia-gmail/venv/bin/python
S=.claude/skills/claudia-holded

$PY $S/inbox.py pending                       # facturas etiquetadas sin procesar (todas las cuentas)
$PY $S/inbox.py download --account <a> --id <msg> --dir <tmp>   # baja los PDFs
$PY $S/inbox.py mark --account <a> --id <msg>                   # aplica etiqueta "procesada"

$PY $S/holded.py contact --nif <NIF>          # busca proveedor por NIF (None si no existe)
$PY $S/holded.py suggest --contact <id>       # cuenta/impuesto/tags de su última compra
$PY $S/holded.py dupcheck --contact <id> --number <n> --total <t> --date <YYYY-MM-DD>
$PY $S/ingest.py --json <datos.json>          # ← VÍA ÚNICA DE CREACIÓN: valida + dedup + crea borrador + adjunta PDF
$PY $S/holded.py suggest --contact <id>       # cuenta/impuesto/tags de su última compra (inspección)

```

> On-demand: las **dudas y ambigüedades se resuelven en el propio chat** de la sesión (no hay avisos asíncronos). `notify.py` queda solo para un eventual modo autónomo futuro.

## Flujo por factura (modo `procesar`)

Se dispara con `/facturas` en Telegram, o pidiéndolo ("procesa las facturas pendientes"). Para cada correo de `inbox.py pending` con PDF:

1. **Descarga el PDF** (`inbox.py download`) y **extrae del PDF** (tú, leyéndolo): razón fiscal del **emisor** (¡no la marca! el emisor real suele estar en el pie), **NIF/CIF**, nº de factura, fecha, base, tipo/cuota de IVA, total, escenario de IVA.
2. **Escribe los campos a un JSON** (supplier_name, nif, number, date, base, total, iva_rate, tax_scenario, pdf=ruta descargada) y pásalo a **`ingest.py --json <fichero>`** — el MISMO helper validado que el ingest por Telegram. Valida, deduplica, calca el histórico y crea el borrador con PDF adjunto. **Nunca uses `holded.py create` a mano** (así ninguna vía puede crear una factura con campos vacíos).
3. **Actúa según el `status`** de ingest.py:
   - `created` → **marca el correo procesado** (`inbox.py mark`).
   - `duplicate` → ya está en Holded → **marca procesado** (`inbox.py mark`).
   - `error` (`DATOS_INCOMPLETOS` / `PROVEEDOR_NO_ENCONTRADO` / `SIN_CONTABILIZACION`) → **NO marques procesado**; anótalo y, al terminar el lote, **pregunta al usuario en el chat** lo que falte (contacto/cuenta/IVA). Cuando responda, reintenta añadiendo `contact_id`/`account`/`tax` al JSON.
4. **Regla de oro** (la aplica `ingest.py`): solo crea si hay proveedor, sin duplicado y con contabilización (histórico/override/aportada). Si falta algo → encolar + notificar, **no subir**.
5. Resume al usuario: creadas, ya existentes, y pendientes de decisión.

> `holded.py` (contact/dupcheck/suggest) sigue siendo útil para inspección manual, pero la **creación va siempre por `ingest.py`**.

## Modo `ingest` (PDF suelto, p.ej. enviado por Telegram)

Para facturas que NO llegan por email y el usuario te pasa directamente (un path de PDF). Igual que el flujo por factura pero SIN pasos de Gmail (no hay correo que etiquetar).

**Antes de nada, clasifica el PDF:** solo sigue aquí si es una **factura de compra de proveedor**. Si es un **extracto bancario** o un **ticket**, es de `claudia-finanzas`, no de Holded (no subas nada). Si dudas, pregunta.

1. **Lee el PDF** (tú) y extrae emisor fiscal real (ojo marca≠emisor), NIF/CIF, nº, fecha, base, tipo/cuota IVA, total, escenario de IVA.
2. **Escribe los campos a un JSON** (supplier_name, nif, number, date, base, total, iva_rate, tax_scenario, pdf) y pásalo a **`ingest.py --json <fichero>`**. Este helper es determinista: valida, deduplica, calca el histórico del proveedor y crea el **borrador con el PDF adjunto**. **No construyas la llamada a la API a mano** (holded.py create) — así se evita crear facturas con campos vacíos.
3. **Actúa según el `status`** que devuelve ingest.py:
   - `created` → informa proveedor/nº/total.
   - `duplicate` → ya existía, no dupliques.
   - `error` con `reason`: `DATOS_INCOMPLETOS` (falta nº/fecha/importe/pdf), `PROVEEDOR_NO_ENCONTRADO`, `SIN_CONTABILIZACION` (proveedor sin histórico → falta cuenta/IVA) → **explica y pregunta al usuario lo que falte; NO subas nada**.
4. Si el usuario aporta lo que faltaba (contacto, cuenta, IVA), añádelo al JSON (`contact_id`/`account`/`tax`) y reintenta `ingest.py`.

`ingest.py` fuerza `draft:true`, pone la **BASE imponible** en la línea (Holded calcula el total con el `p_iva_*`) y se niega a crear si falta algo. Los PDFs entrantes se guardan en `user/workspaces/facturacion/inbox/`.

## Dudas y ambigüedades

Al ser **a demanda**, cuando algo no está claro (proveedor sin identificar, sin histórico de contabilización, posible duplicado) **no subas nada y pregúntalo en el chat de la sesión**. El usuario responde ahí mismo ("usa la cuenta 6290000", "es este proveedor", "súbela igual") y reintentas con esos datos. No hace falta cola ni avisos asíncronos.

## Reglas duras

- **En la duda, no subir.** Es preferible dejar pendiente y avisar que arriesgar un duplicado.
- **Nunca borres** compras existentes ni modifiques facturas de venta.
- Crea en **borrador** por defecto; el usuario confirma en Holded.
- La conciliación bancaria la hace el motor nativo de Holded, no esta skill.
