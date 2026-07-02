#!/usr/bin/env python3
"""
Claudia OS — Cliente de la API de Holded (v2, tokens `pat_`).

Genérico y sin datos de ningún usuario: la API key se lee de
`user/credentials/.env` (`HOLDED_API_KEY`) y la configuración de
`user/config/holded.json`. Ver README.md.

Uso CLI (para pruebas / uso directo):
    python3 holded.py taxes
    python3 holded.py accounts
    python3 holded.py contact --nif B12345678
    python3 holded.py suggest --contact <contact_id>
    python3 holded.py dupcheck --contact <id> --number R123 --total 69.10 --date 2026-07-02
    python3 holded.py create --json payload.json        # crea compra (borrador si config lo pide)
    python3 holded.py attach --id <purchase_id> --file factura.pdf
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import uuid

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDIA_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', '..'))
ENV_FILE = os.path.join(CLAUDIA_ROOT, 'user', 'credentials', '.env')
CONFIG_FILE = os.path.join(CLAUDIA_ROOT, 'user', 'config', 'holded.json')
DEFAULT_BASE = 'https://api.holded.com/api/v2'


def load_env_key():
    """Lee HOLDED_API_KEY de user/credentials/.env sin dependencias externas."""
    if not os.path.exists(ENV_FILE):
        return None
    for line in open(ENV_FILE):
        line = line.strip()
        if line.startswith('HOLDED_API_KEY='):
            return line.split('=', 1)[1].strip()
    return None


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def _num(x):
    """Convierte importes de Holded ('1.234,56' string) o números a float."""
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if ',' in s:  # formato europeo: punto=miles, coma=decimal
        s = s.replace('.', '').replace(',', '.')
    return float(s)


class Holded:
    def __init__(self, api_key=None, config=None):
        self.config = config if config is not None else load_config()
        self.api_key = api_key or load_env_key()
        if not self.api_key:
            raise RuntimeError(
                'Falta HOLDED_API_KEY en user/credentials/.env. '
                'Genera un token en Holded → Configuración → Desarrolladores.'
            )
        self.base = self.config.get('holded', {}).get('api_base', DEFAULT_BASE)

    # --- HTTP ---
    def _request(self, method, path, data=None, multipart=None):
        url = self.base + path
        headers = {'Authorization': f'Bearer {self.api_key}', 'Accept': 'application/json'}
        body = None
        if multipart is not None:
            filename, content = multipart
            boundary = '----claudia' + uuid.uuid4().hex
            parts = [
                ('--' + boundary + '\r\n').encode(),
                (f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n').encode(),
                b'Content-Type: application/pdf\r\n\r\n', content, b'\r\n',
                ('--' + boundary + '--\r\n').encode(),
            ]
            body = b''.join(parts)
            headers['Content-Type'] = f'multipart/form-data; boundary={boundary}'
        elif data is not None:
            body = json.dumps(data).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode()
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            return e.code, {'_error': e.code, '_body': e.read().decode()[:500]}

    def _get_all(self, path, page_key='cursor', max_pages=15):
        """Pagina cursor+limit y devuelve todos los items."""
        items, cursor = [], None
        sep = '&' if '?' in path else '?'
        for _ in range(max_pages):
            p = path + sep + 'limit=100' + (f'&{page_key}={cursor}' if cursor else '')
            st, data = self._get(p)
            batch = data.get('items', []) if isinstance(data, dict) else []
            items += batch
            cursor = data.get('cursor') or data.get('next_cursor') if isinstance(data, dict) else None
            if not batch or not cursor:
                break
        return items

    def _get(self, path):
        return self._request('GET', path)

    # --- Lecturas ---
    def taxes(self):
        return self._get('/taxes')[1].get('items', [])

    def expense_accounts(self):
        return self._get('/expenses-accounts')[1].get('items', [])

    @staticmethod
    def _norm_id(v):
        """Normaliza un identificador fiscal: solo alfanumérico, mayúsculas."""
        return ''.join(ch for ch in str(v or '').upper() if ch.isalnum())

    @classmethod
    def _nif_variants(cls, nif):
        """Variantes de un NIF/CIF para casar con formatos distintos en Holded:
        el propio, sin prefijo de país (ESW0185696B→W0185696B) y con 'ES'."""
        n = cls._norm_id(nif)
        variants = {n}
        m = re.match(r'^([A-Z]{2})([A-Z0-9]+)$', n)
        if m:
            variants.add(m.group(2))          # sin prefijo de país
        if not re.match(r'^[A-Z]{2}', n):
            variants.add('ES' + n)            # con prefijo ES
        return {v for v in variants if v}

    def find_contact_by_nif(self, nif):
        """
        Busca contacto por NIF/CIF de forma robusta. None si no existe.
        1) intento directo por `code` con cada variante (rápido);
        2) fallback: barre contactos y compara (normalizado) contra `code`
           y `vat_number` — necesario porque el `code` suele ir sin prefijo
           de país y el VAT de proveedores UE vive en `vat_number` (y el
           filtro `?vat_number=` de la API no filtra en servidor).
        """
        if not nif:
            return None
        variants = self._nif_variants(nif)
        for cand in variants:
            st, data = self._get(f'/contacts?code={urllib.request.quote(cand)}')
            items = data.get('items', []) if isinstance(data, dict) else []
            if items:
                return items[0]
        for c in self._get_all('/contacts'):
            fields = {self._norm_id(c.get('code')), self._norm_id(c.get('vat_number'))}
            # también el code del contacto sin prefijo de país
            m = re.match(r'^([A-Z]{2})([A-Z0-9]+)$', self._norm_id(c.get('code')))
            if m:
                fields.add(m.group(2))
            if (variants & fields) - {''}:
                return c
        return None

    def last_purchase_for_contact(self, contact_id):
        """Compra más reciente de un contacto (para calcar su contabilización)."""
        purchases = self._get_all(f'/purchases?contact_id={contact_id}')
        if not purchases:
            # fallback: filtrar en cliente si el endpoint no acepta el filtro
            purchases = [p for p in self._get_all('/purchases')
                         if p.get('contact_id') == contact_id]
        purchases.sort(key=lambda p: str(p.get('date', '')), reverse=True)
        return purchases[0] if purchases else None

    def suggest_booking(self, contact_id):
        """
        Deriva cuenta/impuesto/tags de la última compra del proveedor —
        'calcar el histórico' en vez de imponer un criterio fiscal.
        Devuelve {} si el proveedor no tiene compras previas.
        """
        last = self.last_purchase_for_contact(contact_id)
        if not last:
            return {}
        det = self._get(f"/purchases/{last['id']}")[1]
        line = (det.get('lines') or [{}])[0]
        return {
            'account': line.get('account'),
            'tax': (line.get('taxes') or [None])[0],
            'tags': det.get('tags') or [],
            'from_purchase': last.get('document_number'),
        }

    # --- Deduplicación ---
    def find_duplicate(self, contact_id, number=None, total=None, date=None,
                       tolerance=0.02):
        """
        Devuelve dict con el match encontrado y su tipo, o None.
        - 'number'       : mismo nº de documento (duplicado seguro)
        - 'amount_month' : mismo importe y mismo mes (duplicado probable;
                           cubre facturas subidas a mano sin nº)
        Importe+mes evita falsos positivos con recurrentes de igual importe
        en meses distintos.
        """
        purchases = self._get_all('/purchases')
        mine = [p for p in purchases if p.get('contact_id') == contact_id] or purchases
        if number:
            for p in mine:
                if str(p.get('document_number')) == str(number):
                    return {'type': 'number', 'match': p}
        if total is not None and date:
            month = str(date)[:7]
            for p in mine:
                pt = _num(p.get('total'))
                if pt is not None and abs(pt - float(total)) <= tolerance \
                        and str(p.get('date', '')).startswith(month):
                    return {'type': 'amount_month', 'match': p}
        return None

    # --- Escrituras ---
    def create_purchase(self, payload):
        st, data = self._request('POST', '/purchases', data=payload)
        if st not in (200, 201):
            raise RuntimeError(f'create_purchase falló ({st}): {data}')
        return data.get('id') or (data.get('data') or {}).get('id')

    def attach_pdf(self, purchase_id, file_path, filename=None):
        content = open(file_path, 'rb').read()
        fname = filename or os.path.basename(file_path)
        st, data = self._request('POST', f'/purchases/{purchase_id}/attachments',
                                 multipart=(fname, content))
        if st not in (200, 201):
            raise RuntimeError(f'attach_pdf falló ({st}): {data}')
        return data


# --- CLI ---
def _out(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main():
    ap = argparse.ArgumentParser(description='Cliente Holded API v2')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('taxes')
    sub.add_parser('accounts')
    c = sub.add_parser('contact'); c.add_argument('--nif', required=True)
    s = sub.add_parser('suggest'); s.add_argument('--contact', required=True)
    d = sub.add_parser('dupcheck')
    d.add_argument('--contact', required=True)
    d.add_argument('--number'); d.add_argument('--total', type=float); d.add_argument('--date')
    cr = sub.add_parser('create'); cr.add_argument('--json', required=True)
    at = sub.add_parser('attach'); at.add_argument('--id', required=True); at.add_argument('--file', required=True)
    args = ap.parse_args()

    h = Holded()
    if args.cmd == 'taxes':
        _out([{k: t.get(k) for k in ('key', 'name', 'amount', 'scope')} for t in h.taxes()])
    elif args.cmd == 'accounts':
        _out([{k: a.get(k) for k in ('id', 'name', 'account_num')} for a in h.expense_accounts()])
    elif args.cmd == 'contact':
        _out(h.find_contact_by_nif(args.nif))
    elif args.cmd == 'suggest':
        _out(h.suggest_booking(args.contact))
    elif args.cmd == 'dupcheck':
        _out(h.find_duplicate(args.contact, args.number, args.total, args.date))
    elif args.cmd == 'create':
        payload = json.load(open(args.json))
        _out({'id': h.create_purchase(payload)})
    elif args.cmd == 'attach':
        _out(h.attach_pdf(args.id, args.file))


if __name__ == '__main__':
    main()
