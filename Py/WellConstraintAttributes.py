"""Attribute-only well constraint rules, independent of geometry processing."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOKUP = None
LOOKUP_PATH = 'Json/Config/WellConstraintStatus.Local.json'
ALLOWED_TRAJECTORIES = frozenset(['HORIZONTAL', 'DIRECTIONAL'])


def normalize(value):
    return str(value or '').strip().upper()


def configure(root=ROOT):
    global LOOKUP
    path = Path(root)/LOOKUP_PATH
    if not path.exists():
        raise RuntimeError('Missing private well constraint status lookup: '+str(path))
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    lookup = document['mapping']
    if not lookup or any(not key or not isinstance(value,str) or not value or len(value)>6 for key,value in lookup.items()):
        raise ValueError('Invalid well constraint status lookup')
    LOOKUP = {normalize(key):value for key,value in lookup.items()}
    return LOOKUP


def apply(attrs, lookup=None):
    if lookup is None:
        lookup = LOOKUP if LOOKUP is not None else configure()
    result = dict(attrs)
    result['WellConstr'] = 'Y' if attrs.get('WellConstr') == 'Y' and normalize(attrs.get('Trajectory')) in ALLOWED_TRAJECTORIES else 'N'
    result['WelCnsStat'] = lookup.get(normalize(attrs.get('EnvStatus')))
    return result


def rules_hash(root=ROOT):
    lookup=configure(root)
    return hashlib.sha256(json.dumps(dict(version=1,trajectories=sorted(ALLOWED_TRAJECTORIES),lookup=lookup),sort_keys=True).encode()).hexdigest()
