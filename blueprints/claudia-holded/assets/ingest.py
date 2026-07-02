#!/usr/bin/env python3
"""
Claudia OS — Ingesta determinista de UNA factura de compra a Holded.

Pensado para el modo "PDF suelto" (p.ej. facturas enviadas por Telegram).
El modelo SOLO extrae los datos del PDF y los pasa aquí en JSON; este script
VALIDA y crea la compra. Así se evita que el modelo construya la llamada a la
API a mano y se cuele una factura con campos vacíos (número/importe).

REGLA CLAVE: si falta cualquier dato obligatorio (número, fecha, importe,
proveedor, cuenta o impuesto), NO crea nada y devuelve un error tipado para
que el modelo se lo pregunte al usuario. En la duda, no subir.

Entrada JSON (fichero con --json o stdin):
{
  "pdf": "/ruta/al.pdf",            # obligatorio para adjuntar
  "supplier_name": "Proveedor Ejemplo SL",
  "nif": "ESB12345678",             # NIF/CIF/VAT del emisor
  "number": "FAC-2026-001",        # nº de factura (obligatorio)
  "date": "2026-06-19",             # YYYY-MM-DD (obligatorio)
  "base": 70.00,                    # base imponible; o "total"+"iva_rate"
  "total": 70.00,
  "iva_rate": 0,
  "tax_scenario": "reverse_charge_art44",  # ayuda a derivar el impuesto
  "tax": "p_iva_0",                 # opcional; si no, se deriva de histórico/escenario
  "account": "62900000",            # opcional; si no, del histórico del proveedor
  "tags": ["proyectos"],            # opcional
  "contact_id": "..."               # opcional (fuerza el contacto)
}

Salida JSON: {"status":"created"|"error", ...}. Exit 0 si created, !=0 si error.

Uso:
    python3 ingest.py --json datos.json
    echo '{...}' | python3 ingest.py
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import holded  # noqa: E402


def derive_base(d):
    if d.get('base') is not None:
        return round(float(d['base']), 2)
    if d.get('total') is not None and d.get('iva_rate') is not None:
        return round(float(d['total']) / (1 + float(d['iva_rate']) / 100), 2)
    return None


def derive_tax(d):
    """Impuesto de compra: explícito > por escenario+tipo."""
    if d.get('tax'):
        return d['tax']
    scen = (d.get('tax_scenario') or '').lower()
    rate = d.get('iva_rate')
    if scen in ('reverse_charge_art44', 'intracom_servicios', 'intracom_bienes', 'exento') \
            or (rate is not None and float(rate) == 0):
        return 'p_iva_0'          # el usuario contabiliza el reverse charge como 0% (patrón histórico)
    if rate is not None:
        r = int(float(rate))
        return f'p_iva_{r}'
    return None


def fail(reason, detail='', **extra):
    print(json.dumps({'status': 'error', 'reason': reason, 'detail': detail, **extra},
                     ensure_ascii=False))
    sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', help='fichero JSON con los datos (o stdin)')
    args = ap.parse_args()
    raw = open(args.json).read() if args.json else sys.stdin.read()
    d = json.loads(raw)

    H = holded.Holded()
    ov = H.config.get('supplier_overrides', {})

    # --- validación de campos base ---
    missing = [k for k in ('number', 'date') if not d.get(k)]
    base = derive_base(d)
    if base is None or base <= 0:
        missing.append('importe (base/total)')
    if not d.get('pdf') or not os.path.exists(d['pdf']):
        missing.append('pdf')
    if missing:
        fail('DATOS_INCOMPLETOS', f"Faltan: {', '.join(missing)}. No se crea nada.",
             missing=missing)

    # --- proveedor ---
    o = ov.get(holded.Holded._norm_id(d.get('nif', ''))) or ov.get(d.get('nif'))
    contact_id = d.get('contact_id') or (o.get('contact_id') if o else None)
    if not contact_id:
        c = H.find_contact_by_nif(d.get('nif'))
        if not c:
            fail('PROVEEDOR_NO_ENCONTRADO',
                 f"No hay contacto con NIF {d.get('nif')} ({d.get('supplier_name')}). "
                 f"No se crea a ciegas: indica el contacto o si crearlo.",
                 nif=d.get('nif'), supplier=d.get('supplier_name'))
        contact_id = c['id']

    # --- dedup ---
    dup = H.find_duplicate(contact_id, number=d.get('number'), total=d.get('total'),
                           date=d.get('date'),
                           tolerance=H.config.get('dedup', {}).get('amount_tolerance', 0.02))
    if dup:
        m = dup['match']
        print(json.dumps({'status': 'duplicate', 'dup_type': dup['type'],
                          'existing': {'id': m.get('id'), 'number': m.get('document_number'),
                                       'total': m.get('total'), 'date': m.get('date')}},
                         ensure_ascii=False))
        sys.exit(0)

    # --- contabilización (calcar histórico si no viene dada) ---
    sug = o if o else H.suggest_booking(contact_id)
    account = d.get('account') or (sug.get('account') if sug else None)
    tax = derive_tax(d) or (sug.get('tax') if sug else None)
    tags = d.get('tags') if d.get('tags') is not None else (sug.get('tags') if sug else [])
    faltan_book = []
    if not account:
        faltan_book.append('cuenta contable')
    if not tax:
        faltan_book.append('impuesto (IVA)')
    if faltan_book:
        fail('SIN_CONTABILIZACION',
             f"Proveedor sin histórico que calcar; faltan: {', '.join(faltan_book)}. "
             f"Indícalos y reintento (no invento la cuenta).",
             need=faltan_book, contact_id=contact_id)

    # --- crear borrador + adjuntar ---
    payload = {
        'contact_id': contact_id, 'date': d['date'], 'number': str(d['number']),
        'currency': 'EUR', 'draft': True, 'tags': tags or [],
        'notes': 'Alta automática (ingest PDF) – Claudia OS',
        'items': [{
            'name': f"{d.get('supplier_name', 'Factura')} · {d['number']}",
            'units': 1, 'price': base, 'taxes': [tax], 'account': account,
        }],
    }
    pid = H.create_purchase(payload)
    H.attach_pdf(pid, d['pdf'], filename=os.path.basename(d['pdf']))
    det = H._get(f"/purchases/{pid}")[1]
    print(json.dumps({'status': 'created', 'id': pid, 'number': det.get('document_number'),
                      'total': det.get('total'), 'date': det.get('date'),
                      'draft': det.get('draft'), 'base_usada': base, 'tax': tax,
                      'account': account}, ensure_ascii=False))


if __name__ == '__main__':
    main()
