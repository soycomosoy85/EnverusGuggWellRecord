"""Preserve full text in geodatabase fields."""
import json


def required_widths(fields, payloads, current):
    text = [f for f in fields if f['exportType'] == 'TEXT']
    wanted = {}
    for payload in payloads:
        attrs = json.loads(payload)
        for field in text:
            name = field['fieldName']
            value = attrs.get(name)
            if value is None:
                continue
            size = len(str(value))
            if name == 'WellConstr' and (value not in ('Y', 'N') or size != 1):
                raise ValueError('WellConstr must be Y or N; its width remains one')
            if size > current[name]:
                wanted[name] = max(wanted.get(name, 0), max(64, 1 << (size - 1).bit_length()))
    return wanted

