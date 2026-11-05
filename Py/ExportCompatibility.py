"""Explicit cache compatibility for the November 2026 text-writer repair.

Only the exact reviewed source revision is compatible. Geometry, selection,
enrichment, templates, references and configuration are otherwise unchanged.
Unknown code hashes retain ordinary computation-cache invalidation.
"""
PREVIOUS_LOGIC_HASH = '56f2bb641b14dc66bac648d55aa6f772bbf1b11f31c7949abb473ee2511c97c5'
WRITER_REPAIR_LOGIC_HASH = 'be70165e3c89596d79df60a2b44ab141e66d6cc511a276382fa462a29a43aae3'
ATTRIBUTE_REPAIR_LOGIC_HASH = 'c7465bfef9f702fe87ff0b27122b00f3fc1fdd362f0ab47e97aca4f9f96bd431'


def compatible_logic_hash(value):
    return PREVIOUS_LOGIC_HASH if value in {WRITER_REPAIR_LOGIC_HASH,ATTRIBUTE_REPAIR_LOGIC_HASH} else value


def geometry_fields(fields):
    """A derived status column changes attributes, not the cached well geometry."""
    result=[dict(f) for f in fields if f['fieldName']!='WelCnsStat']
    for order,field in enumerate(result,1):field['order']=order
    return result
