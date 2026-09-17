"""Fingerprint executable report rules without changing the visible version."""
import hashlib
from pathlib import Path


def pipeline_fingerprint():
    root=Path(__file__).resolve().parent
    digest=hashlib.sha256()
    for path in sorted([*root.glob('crm_*.py'),root/'run_crm_aftersales_daily.sh']):
        digest.update(path.name.encode()+b'\0'+path.read_bytes()+b'\0')
    return digest.hexdigest()
