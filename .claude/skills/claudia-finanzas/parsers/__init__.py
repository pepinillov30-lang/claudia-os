"""
Parsers de extractos bancarios.

Cada parser implementa:
- detect(header_line: str) -> bool
- parse(content: str) -> list[dict]

El dict de salida tiene: fecha, concepto, importe, saldo (opcional)
"""

import importlib
import pkgutil

def detect_and_parse(content: str) -> tuple[str, list[dict]]:
    """Detecta el formato del extracto y lo parsea.

    Returns: (bank_name, records)
    Raises ValueError if no parser matches.
    """
    for importer, modname, ispkg in pkgutil.iter_modules(__path__):
        if modname.startswith('_'):
            continue
        mod = importlib.import_module(f'.{modname}', __package__)
        first_line = content.split('\n')[0]
        if hasattr(mod, 'detect') and mod.detect(first_line):
            return (modname, mod.parse(content))
    raise ValueError(
        "No se ha reconocido el formato del extracto. "
        "Comparte las primeras líneas del CSV para crear un parser."
    )
