"""
Parser genérico CSV — fallback cuando no matchea ningún parser específico de banco.
Intenta detectar columnas por nombre (fecha, concepto/descripcion, importe/cantidad, saldo).
"""

import csv
import io
import re
from datetime import datetime

FECHA_COLS = ['fecha', 'date', 'fecha_operacion', 'fecha operación', 'f.operación', 'f.valor']
CONCEPTO_COLS = ['concepto', 'descripcion', 'descripción', 'description', 'detalle', 'movimiento']
IMPORTE_COLS = ['importe', 'cantidad', 'amount', 'monto', 'cargo/abono', 'importe (eur)']
SALDO_COLS = ['saldo', 'balance', 'saldo disponible', 'saldo contable']

DATE_FORMATS = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d/%m/%y', '%Y/%m/%d']


def detect(header_line: str) -> bool:
    header_lower = header_line.lower()
    has_fecha = any(col in header_lower for col in FECHA_COLS)
    has_concepto = any(col in header_lower for col in CONCEPTO_COLS)
    has_importe = any(col in header_lower for col in IMPORTE_COLS)
    return has_fecha and (has_concepto or has_importe)


def _find_col(headers: list[str], candidates: list[str]) -> int | None:
    for i, h in enumerate(headers):
        if h.lower().strip() in candidates:
            return i
    return None


def _parse_date(val: str) -> str:
    val = val.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(val, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return val


def _parse_amount(val: str) -> float:
    val = val.strip().replace('€', '').replace(' ', '')
    val = re.sub(r'\.(\d{3})', r'\1', val)
    val = val.replace(',', '.')
    return float(val)


def parse(content: str) -> list[dict]:
    reader = csv.reader(io.StringIO(content), delimiter=_detect_delimiter(content))
    headers = next(reader)

    idx_fecha = _find_col(headers, FECHA_COLS)
    idx_concepto = _find_col(headers, CONCEPTO_COLS)
    idx_importe = _find_col(headers, IMPORTE_COLS)
    idx_saldo = _find_col(headers, SALDO_COLS)

    if idx_fecha is None or idx_importe is None:
        raise ValueError("No se encontraron columnas de fecha e importe")

    records = []
    for row in reader:
        if not row or all(c.strip() == '' for c in row):
            continue
        try:
            record = {
                'fecha': _parse_date(row[idx_fecha]),
                'concepto': row[idx_concepto].strip() if idx_concepto is not None else '',
                'importe': _parse_amount(row[idx_importe]),
                'saldo': _parse_amount(row[idx_saldo]) if idx_saldo is not None else None,
            }
            records.append(record)
        except (ValueError, IndexError):
            continue

    return records


def _detect_delimiter(content: str) -> str:
    first_line = content.split('\n')[0]
    if '\t' in first_line:
        return '\t'
    if ';' in first_line and ',' not in first_line:
        return ';'
    if first_line.count(';') > first_line.count(','):
        return ';'
    return ','
