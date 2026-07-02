#!/usr/bin/env python3
"""
Claudia OS — Notificación + cola de decisiones para facturación Holded.

Cuando una factura no se sube automáticamente (duda, posible duplicado,
IVA incierto...), se registra en una cola y se avisa al usuario por el
canal configurado (Telegram o email). El usuario responde y otra pasada
resuelve la decisión.

Genérico: canal en `user/config/holded.json`; credenciales en
`user/credentials/.env` (TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID, SMTP_*).

Motivos tipados sugeridos:
    DUP_SOSPECHADO · IVA_INCIERTO · PROVEEDOR_AMBIGUO · SIN_PDF ·
    CUENTA_DESCONOCIDA · IMPORTE_NO_CUADRA

Uso CLI:
    python3 notify.py queue --file caso.json     # añade caso a la cola y notifica
    python3 notify.py list                        # lista pendientes
    python3 notify.py send --text "mensaje"       # notificación suelta
"""

import argparse
import json
import os
import smtplib
import urllib.request
import urllib.parse
from email.mime.text import MIMEText

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLAUDIA_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', '..'))
ENV_FILE = os.path.join(CLAUDIA_ROOT, 'user', 'credentials', '.env')
CONFIG_FILE = os.path.join(CLAUDIA_ROOT, 'user', 'config', 'holded.json')


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip()
    return env


def load_config():
    return json.load(open(CONFIG_FILE)) if os.path.exists(CONFIG_FILE) else {}


def _queue_path(cfg):
    rel = cfg.get('queue_file', 'user/workspaces/facturacion/pending.json')
    path = os.path.join(CLAUDIA_ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def load_queue(cfg):
    p = _queue_path(cfg)
    return json.load(open(p)) if os.path.exists(p) else []


def save_queue(cfg, items):
    json.dump(items, open(_queue_path(cfg), 'w'), ensure_ascii=False, indent=2)


# --- Canales ---
def send_telegram(env, text):
    token = env.get('TELEGRAM_BOT_TOKEN'); chat = env.get('TELEGRAM_USER_ID')
    if not token or not chat:
        return False, 'faltan TELEGRAM_BOT_TOKEN / TELEGRAM_USER_ID'
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = urllib.parse.urlencode({'chat_id': chat, 'text': text, 'parse_mode': 'HTML'}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
            return r.status == 200, r.read().decode()[:120]
    except Exception as e:
        return False, str(e)[:150]


def send_email(env, cfg, text, subject='Facturación: revisión pendiente'):
    to = cfg.get('notifications', {}).get('email_to') or env.get('EMAIL_TO')
    frm = env.get('EMAIL_FROM') or env.get('SMTP_USER')
    host, port = env.get('SMTP_HOST'), int(env.get('SMTP_PORT', 587))
    if not (to and frm and host):
        return False, 'faltan SMTP_* / EMAIL_TO'
    msg = MIMEText(text, 'plain', 'utf-8')
    msg['Subject'], msg['From'], msg['To'] = subject, frm, to
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            if env.get('SMTP_USER'):
                s.login(env['SMTP_USER'], env.get('SMTP_PASSWORD', ''))
            s.sendmail(frm, [to], msg.as_string())
        return True, 'enviado'
    except Exception as e:
        return False, str(e)[:150]


def notify(cfg, env, text):
    channel = cfg.get('notifications', {}).get('channel', 'telegram')
    if channel == 'email':
        return send_email(env, cfg, text)
    return send_telegram(env, text)


def _fmt(case):
    return (
        f"🧾 <b>Factura pendiente de revisión</b>\n"
        f"Motivo: <b>{case.get('reason')}</b>\n"
        f"Proveedor: {case.get('supplier')} ({case.get('nif','?')})\n"
        f"Nº: {case.get('number','—')} · {case.get('date','')}\n"
        f"Total: {case.get('total')} €\n"
        f"{case.get('detail','')}\n"
        f"Responde: «súbela» · «ignórala» · «cuenta XXXX»"
    )


def queue_case(cfg, env, case):
    """Añade un caso a la cola y notifica. `case` es un dict con al menos
    reason, supplier, total, y el message_id/account de origen."""
    items = load_queue(cfg)
    case.setdefault('status', 'pending')
    items.append(case)
    save_queue(cfg, items)
    ok, info = notify(cfg, env, _fmt(case))
    return {'queued': True, 'notified': ok, 'info': info, 'pending_total': len(items)}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    q = sub.add_parser('queue'); q.add_argument('--file', required=True)
    sub.add_parser('list')
    s = sub.add_parser('send'); s.add_argument('--text', required=True)
    args = ap.parse_args()
    cfg, env = load_config(), load_env()

    if args.cmd == 'queue':
        case = json.load(open(args.file))
        print(json.dumps(queue_case(cfg, env, case), ensure_ascii=False))
    elif args.cmd == 'list':
        print(json.dumps([c for c in load_queue(cfg) if c.get('status') == 'pending'],
                         ensure_ascii=False, indent=2))
    elif args.cmd == 'send':
        ok, info = notify(cfg, env, args.text)
        print(json.dumps({'sent': ok, 'info': info}, ensure_ascii=False))


if __name__ == '__main__':
    main()
