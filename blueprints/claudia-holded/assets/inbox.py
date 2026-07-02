#!/usr/bin/env python3
"""
Claudia OS — Bandeja de facturas para Holded.

Escanea las cuentas de Gmail configuradas, encuentra los correos con la
etiqueta de origen que aún NO están procesados, y descarga sus PDFs.
Reutiliza la autenticación de la skill `claudia-gmail` (tokens de usuario).

Genérico: cuentas y etiquetas se leen de `user/config/holded.json`.

Uso CLI:
    python3 inbox.py pending [--account <alias>]     # lista facturas sin procesar (JSON)
    python3 inbox.py download --account <alias> --id <msg_id> --dir <destino>
    python3 inbox.py mark --account <alias> --id <msg_id>   # aplica etiqueta "procesada"
"""

import argparse
import base64
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDIA_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', '..'))
GMAIL_SKILL = os.path.join(CLAUDIA_ROOT, '.claude', 'skills', 'claudia-gmail')
CONFIG_FILE = os.path.join(CLAUDIA_ROOT, 'user', 'config', 'holded.json')

sys.path.insert(0, GMAIL_SKILL)
import gmail  # noqa: E402  (infra de auth compartida)


def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise RuntimeError(f'Falta configuración: {CONFIG_FILE} (ver config.example.json)')
    with open(CONFIG_FILE) as f:
        return json.load(f)


def _label_id(svc, name):
    labels = svc.users().labels().list(userId='me').execute().get('labels', [])
    lab = next((l for l in labels if l['name'].lower() == name.lower()), None)
    return lab['id'] if lab else None


def _ensure_label(svc, name):
    lid = _label_id(svc, name)
    if lid:
        return lid
    lab = svc.users().labels().create(userId='me', body={'name': name}).execute()
    return lab['id']


def _pdf_parts(payload):
    """Devuelve [(filename, attachmentId)] de los PDF del mensaje."""
    out = []

    def walk(p):
        fn = p.get('filename', '')
        if fn.lower().endswith('.pdf'):
            aid = p.get('body', {}).get('attachmentId')
            if aid:
                out.append((fn, aid))
        for sp in p.get('parts', []) or []:
            walk(sp)
    walk(payload)
    return out


def pending(cfg, only_account=None):
    """Correos con etiqueta de origen y sin la de procesado, en todas las cuentas."""
    g = cfg['gmail']
    src, done = g['source_label'], g['processed_label']
    accounts = [only_account] if only_account else g['accounts']
    results = []
    for acc in accounts:
        try:
            svc = gmail.get_service(acc)
        except SystemExit:
            results.append({'account': acc, 'error': 'token no válido — reautoriza con auth.py'})
            continue
        src_id = _label_id(svc, src)
        if not src_id:
            continue
        done_id = _label_id(svc, done)
        q = svc.users().messages().list(userId='me', labelIds=[src_id], maxResults=200).execute()
        for m in q.get('messages', []):
            full = svc.users().messages().get(userId='me', id=m['id'], format='full').execute()
            labs = full.get('labelIds', [])
            if done_id and done_id in labs:
                continue  # ya procesado
            h = {x['name']: x['value'] for x in full['payload']['headers']}
            pdfs = _pdf_parts(full['payload'])
            results.append({
                'account': acc,
                'id': m['id'],
                'from': h.get('From', ''),
                'subject': h.get('Subject', ''),
                'date': h.get('Date', ''),
                'pdfs': [fn for fn, _ in pdfs],
                'has_pdf': bool(pdfs),
            })
    return results


def download(cfg, account, msg_id, dest_dir):
    svc = gmail.get_service(account)
    os.makedirs(dest_dir, exist_ok=True)
    full = svc.users().messages().get(userId='me', id=msg_id, format='full').execute()
    saved = []
    for fn, aid in _pdf_parts(full['payload']):
        att = svc.users().messages().attachments().get(
            userId='me', messageId=msg_id, id=aid).execute()
        data = base64.urlsafe_b64decode(att['data'])
        safe = fn.replace('/', '_')
        path = os.path.join(dest_dir, safe)
        with open(path, 'wb') as f:
            f.write(data)
        saved.append(path)
    return saved


def mark_processed(cfg, account, msg_id):
    svc = gmail.get_service(account)
    lid = _ensure_label(svc, cfg['gmail']['processed_label'])
    svc.users().messages().modify(userId='me', id=msg_id, body={'addLabelIds': [lid]}).execute()
    return True


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('pending'); p.add_argument('--account')
    d = sub.add_parser('download')
    d.add_argument('--account', required=True); d.add_argument('--id', required=True)
    d.add_argument('--dir', required=True)
    m = sub.add_parser('mark')
    m.add_argument('--account', required=True); m.add_argument('--id', required=True)
    args = ap.parse_args()
    cfg = load_config()

    if args.cmd == 'pending':
        print(json.dumps(pending(cfg, args.account), ensure_ascii=False, indent=2))
    elif args.cmd == 'download':
        print(json.dumps({'saved': download(cfg, args.account, args.id, args.dir)}, ensure_ascii=False))
    elif args.cmd == 'mark':
        mark_processed(cfg, args.account, args.id)
        print(json.dumps({'status': 'procesado', 'id': args.id}))


if __name__ == '__main__':
    main()
