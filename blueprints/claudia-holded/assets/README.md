# claudia-holded

Automatiza la entrada de **facturas de compra de proveedores** en Holded, para
cualquier usuario de Claudia OS que use Holded. La skill no contiene datos de
ningún usuario: todo (cuentas, etiquetas, credenciales, canal de aviso, reglas
por proveedor) se lee de las carpetas de usuario.

## Qué hace

1. Lee los correos con una etiqueta de origen en las cuentas de Gmail configuradas.
2. Extrae los datos del PDF de la factura (proveedor, NIF, nº, fecha, base, IVA, total).
3. Comprueba que **no** sea un duplicado (por nº, o por importe + mes si se subió sin nº).
4. Crea la compra en Holded **calcando la contabilización histórica** del proveedor
   (cuenta, impuesto, tags) y **adjunta el PDF**.
5. Marca el correo como procesado.
6. Ante cualquier duda (posible duplicado, IVA incierto, proveedor ambiguo…)
   **no sube nada**: encola el caso y avisa por Telegram/email. El usuario responde
   y una segunda pasada resuelve.

La conciliación con el banco la hace el **motor nativo de Holded**, no esta skill.

## Setup

1. **API key de Holded** (API v2, token `pat_`): Holded → Configuración → Desarrolladores.
   Guárdala en `user/credentials/.env`:
   ```
   HOLDED_API_KEY=pat_xxxxxxxx
   ```
   Es **por empresa**: usa la de la sociedad donde registras las compras.

2. **Cuentas de Gmail**: autorízalas con la skill `claudia-gmail`:
   ```
   python3 .claude/skills/claudia-gmail/auth.py <alias>
   ```
   En Gmail, crea una etiqueta de origen (p.ej. `Facturas`) y un filtro que la
   aplique a los correos de facturas por remitente/asunto.

3. **Configuración**: copia `config.example.json` a `user/config/holded.json` y
   rellena tus cuentas, etiquetas y canal de notificación.

4. **Notificaciones**: usa las credenciales ya presentes en `.env`
   (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_USER_ID`, o `SMTP_*` + `EMAIL_TO`).

## Uso

```
/claudia-holded procesar     # procesa las facturas pendientes
/claudia-holded pendientes   # lista casos que esperan tu decisión
/claudia-holded resolver     # aplica tus respuestas a los casos en cola
```

Ver `SKILL.md` para el detalle del flujo y los helpers (`holded.py`, `inbox.py`, `notify.py`).

## Notas de la API

- API **v2**: base `https://api.holded.com/api/v2`, auth `Authorization: Bearer pat_...`.
  (La API *legacy* `invoicing/v1` con header `key` NO acepta tokens `pat_`.)
- Contactos por NIF: el NIF vive en el campo `code`.
- Compras: recurso `/purchases`; adjuntar PDF en `multipart/form-data` a
  `/purchases/{id}/attachments`. Impuesto de compra con prefijo `p_` (`GET /taxes`).
