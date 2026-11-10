"""Explicit cache compatibility for the November 2026 text-writer repair.

Only the exact reviewed source revision is compatible. Geometry, selection,
enrichment, templates, references and configuration are otherwise unchanged.
Unknown code hashes retain ordinary computation-cache invalidation.
"""
PREVIOUS_LOGIC_HASH = '56f2bb641b14dc66bac648d55aa6f772bbf1b11f31c7949abb473ee2511c97c5'
WRITER_REPAIR_LOGIC_HASH = 'be70165e3c89596d79df60a2b44ab141e66d6cc511a276382fa462a29a43aae3'
ATTRIBUTE_REPAIR_LOGIC_HASH = 'c7465bfef9f702fe87ff0b27122b00f3fc1fdd362f0ab47e97aca4f9f96bd431'

GEODATABASE_ONLY_LOGIC_HASH = 'd8b937d118a513d97152afb9a3fbffca5f7f2239f5231eeede7244b60b3bb85e'
DOCUMENTATION_CLEANUP_LOGIC_HASH = '1faa8893d409a26cf9acf1cd94ad46e0e63ffa6366ff6a3ee143c65d12c28a05'

def compatible_logic_hash(value):
    return PREVIOUS_LOGIC_HASH if value in {WRITER_REPAIR_LOGIC_HASH,ATTRIBUTE_REPAIR_LOGIC_HASH,GEODATABASE_ONLY_LOGIC_HASH,DOCUMENTATION_CLEANUP_LOGIC_HASH} else value


def compatible_rules_hash(value):
    # Reviewed delivery-description edits only. The complete hash includes
    # references, Pro version, geometry configuration, fields and header schema.
    # A different input combination is never treated as compatible implicitly.
    return {'595ce27b53d9baea14aba26b8e9d0f72be56f95fab64e479140b753a81fdaaa1':
            'a05050e77c239383aad6b43f170293d2b010bbd27c3381af25248b4077115305'}.get(value,value)


def geometry_fields(fields):
    """A derived status column changes attributes, not the cached well geometry."""
    result=[dict(f) for f in fields if f['fieldName']!='WelCnsStat']
    for order,field in enumerate(result,1):field['order']=order
    return result
