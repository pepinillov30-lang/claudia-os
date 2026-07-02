---
name: claudia-holded
version: 1.0.0
scope: addon
toca: .claude/skills/claudia-holded/, user/config/holded.json, user/credentials/.env (HOLDED_API_KEY), (opcional) .claude/skills/telegram-bot/src/index.js
reversibilidad: rm -rf .claude/skills/claudia-holded/ user/config/holded.json  (+ revertir el handler de Telegram si se instaló el paso opcional)
riesgo: medio — instala una skill que ESCRIBE en Holded (siempre en borrador y con validación previa); requiere la skill claudia-gmail configurada y una API key de Holded
assets:
  - source: assets/SKILL.md
    target: .claude/skills/claudia-holded/SKILL.md
  - source: assets/holded.py
    target: .claude/skills/claudia-holded/holded.py
  - source: assets/ingest.py
    target: .claude/skills/claudia-holded/ingest.py
  - source: assets/inbox.py
    target: .claude/skills/claudia-holded/inbox.py
  - source: assets/notify.py
    target: .claude/skills/claudia-holded/notify.py
  - source: assets/config.example.json
    target: .claude/skills/claudia-holded/config.example.json
  - source: assets/README.md
    target: .claude/skills/claudia-holded/README.md
  - source: assets/behavior.md
    target: .claude/skills/claudia-holded/user/behavior.md
---

# Blueprint: claudia-holded

Instala la skill `/claudia-holded`: automatiza la entrada de **facturas de compra de proveedores** en Holded. Lee correos etiquetados en Gmail, extrae los datos del PDF, comprueba duplicados y crea la compra en Holded **como borrador** con el PDF adjunto, calcando la contabilización histórica de cada proveedor. Ante cualquier duda no sube nada y lo pregunta en el chat.

Es una integración **opt-in y nicho** (solo tiene sentido si usas Holded), por eso se distribuye como blueprint y no viene de serie.

**Dependencias:** requiere la skill `claudia-gmail` ya configurada (reutiliza sus tokens) y una **API key de Holded (API v2, token `pat_`)**. El envío de facturas por Telegram es opcional y requiere la skill `telegram-bot`.

---

## Paso 1 — Metadatos

Ver frontmatter arriba. Manifest de 8 assets (la skill) + creación de `user/config/holded.json` + (opcional) un handler en el bot de Telegram.

---

## Paso 2 — Discovery

Antes de proponer nada, lee y toma nota. **No actúes — solo observa.**

1. **Colisión** — lista `.claude/skills/*/SKILL.md`. Si ya existe `claudia-holded`, para y avisa.

2. **Dependencia Gmail** — ¿existe la skill `claudia-gmail` y cuentas autorizadas?
   - Candidatos: `.claude/skills/claudia-gmail/` y tokens en `user/credentials/gmail/tokens/*.json`.
   - Anota los **alias de cuenta** disponibles (nombre de cada `*.json`). Si no hay tokens, regístralo: el usuario tendrá que autorizar Gmail antes de usar la skill.

3. **API key de Holded** — ¿existe `HOLDED_API_KEY` en `user/credentials/.env`?
   - Si no está o está vacía, regístralo: hay que generarla (Holded → Configuración → Desarrolladores, API v2). Es **por empresa**.

4. **Telegram (opcional)** — ¿existe la skill `telegram-bot` con `src/index.js`?
   - Si existe, el paso opcional de "subir factura suelta por Telegram" es aplicable. Si no, se omite sin error.

5. **Convención de etiquetas** — pregunta al usuario qué etiqueta de Gmail usará como cola de facturas y cuál para las procesadas (por defecto `Facturas` / `Procesada`, o anidadas tipo `Claudia OS/Facturas`).

6. **Identidad/tono** — lee `user/context/identity.md` solo para tono del resumen, no como dato.

Al terminar tienes: cuentas Gmail reales, si hay API key, si hay Telegram, y la convención de etiquetas. Eso alimenta el Paso 3.

---

## Paso 3 — Propuesta adaptada + confirmación

Muestra un resumen con lo **realmente detectado**, no la plantilla genérica:

```
He revisado tu instancia. Propongo instalar /claudia-holded:

**Detectado:**
- Cuentas Gmail disponibles: <alias reales, o "ninguna → habrá que autorizar">
- API key de Holded: <presente / ausente → hay que generarla>
- Telegram: <disponible → incluyo el envío de PDF / no disponible → lo omito>

**Voy a crear:**
- .claude/skills/claudia-holded/ (skill: SKILL.md, holded.py, ingest.py, inbox.py, notify.py, config.example.json, README.md, user/behavior.md)
- user/config/holded.json (con las cuentas <detectadas> y las etiquetas <elegidas>)
- (opcional, si aceptas) un handler de documentos PDF en el bot de Telegram

**No voy a tocar** nada existente salvo, si lo autorizas, añadir el handler al bot.
**Tú tendrás que** poner HOLDED_API_KEY en user/credentials/.env <si falta> y crear las etiquetas/filtros en Gmail.

¿OK, o ajustamos (cuentas, etiquetas, sin Telegram...)?
```

**Espera OK explícito.** Si redirige, ajusta y vuelve a pedir OK.

---

## Paso 4 — Pre-flight

**Bloquear y parar si:**
- `git status --porcelain -- .claude/skills/claudia-holded/ user/config/holded.json` devuelve cualquier línea.
- Hay un merge/rebase en curso.
- `.claude/skills/claudia-holded/` ya existe (colisión no detectada en Discovery).

**Avisar pero no bloquear si:**
- Hay cambios sin commit en otras rutas. Recuérdale que para un rollback limpio conviene commitear/stashear antes. Él decide.
- No hay `HOLDED_API_KEY` o no hay cuentas Gmail: la skill se instala igual, pero no funcionará hasta completarlos. Déjalo claro.

---

## Paso 5 — Cambios

1. Crea `.claude/skills/claudia-holded/` y `.claude/skills/claudia-holded/user/`. Copia los 8 assets a sus `target` (ver manifest). Los ficheros son genéricos, no llevan marcadores `<!-- ADAPTAR -->`.

2. **Config del usuario** — copia `assets/config.example.json` a `user/config/holded.json` y rellénalo con lo detectado en Discovery:
   - `gmail.accounts`: los alias reales de Gmail del usuario.
   - `gmail.source_label` / `gmail.processed_label`: las etiquetas elegidas en el Paso 2.5.
   - Deja `supplier_overrides` vacío (se llena con el uso).
   - **No** pongas aquí la API key: recuérdale que va en `user/credentials/.env` como `HOLDED_API_KEY=`.

3. **API key** — si en Discovery no había `HOLDED_API_KEY`, añade la línea vacía `HOLDED_API_KEY=` a `user/credentials/.env` (si no existe ya) y avisa al usuario de que la rellene.

4. **(OPCIONAL) Ingesta por Telegram** — solo si el usuario aceptó y existe `telegram-bot`. Añade a `.claude/skills/telegram-bot/src/index.js`, **antes** de `// --- Handler principal ---`, un handler `bot.on('document')` que: descarta lo que no sea PDF; guarda el PDF en `user/workspaces/facturacion/inbox/`; y llama a `handlePrompt` con un prompt que (0) clasifique el documento (factura de compra → claudia-holded; extracto/ticket → claudia-finanzas; duda → pregunta) y, si es factura, extraiga los campos, escriba un JSON y lo pase a `ingest.py --json`, reportando su `status`. Añade también un comando `/facturas` que lance el modo procesar. **Valida la sintaxis** (`node --check`) y reinicia el bot (`pm2 restart`). Si el usuario no lo quiere, omite este paso entero — la skill funciona igual por email/sesión.

5. Si al terminar quedara cualquier marcador `<!-- ADAPTAR -->` vivo en algún fichero, **revertir**.

---

## Paso 6 — Post

**No commitees nada.** Se aplica, se revisa, commitea el usuario.

- Muestra `git status` y `git diff --stat HEAD -- .claude/skills/claudia-holded/ user/config/holded.json`.
- Recuerda:
  - **Rollback:** `rm -rf .claude/skills/claudia-holded/ user/config/holded.json` (+ revertir index.js si se tocó).
  - **Commit cuando conforme:** `feat: add claudia-holded skill via blueprint v1.0.0`
  - **Pendiente del usuario:** generar la API key de Holded (si falta), autorizar cuentas Gmail (si faltan) y crear la etiqueta/filtro en Gmail.

---

## Paso 7 — Verificación

Solo si hay `HOLDED_API_KEY` y al menos una cuenta Gmail. Con el intérprete que tenga las libs de Google (venv de claudia-gmail):

1. **Conexión Holded:** `python3 .claude/skills/claudia-holded/holded.py taxes` devuelve la lista de impuestos (no error 401/`Invalid key`). Si falla, revisa que la key sea de la **API v2** (`pat_`), no la legacy.
2. **Contacto por NIF:** `holded.py contact --nif <un NIF de proveedor real que exista en su Holded>` lo encuentra.
3. **Bandeja:** `inbox.py pending` lista los correos etiquetados sin procesar (o vacío si no hay).
4. **Guard de creación:** `ingest.py` con un JSON sin número devuelve `{"status":"error","reason":"DATOS_INCOMPLETOS"}` — confirma que **no crea facturas incompletas**.
5. (Opcional) Si se instaló Telegram: enviar un PDF de factura al bot crea un borrador en Holded o pregunta si falta algo.

Si algún check falla, para y debug antes de dar el blueprint por aplicado.
