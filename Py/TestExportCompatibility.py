"""Only explicitly reviewed processing keys may reuse prior geometry caches."""
import hashlib,unittest
from pathlib import Path
from ExportCompatibility import compatible_logic_hash,compatible_rules_hash,PREVIOUS_LOGIC_HASH,DOCUMENTATION_CLEANUP_LOGIC_HASH


class CompatibilityTests(unittest.TestCase):
    def test_reviewed_logic_is_exact(self):
        root=Path(__file__).resolve().parent
        names=['Identity.py','WellGeometry.py','Selection.py','GuggEnrichment.py','WellRecordCalculations.py','BuildProducts.py','ManagedProducts.py']
        actual=hashlib.sha256(''.join((root/n).read_text(encoding='utf-8-sig') for n in names).encode()).hexdigest()
        self.assertEqual(actual,DOCUMENTATION_CLEANUP_LOGIC_HASH)
        self.assertEqual(compatible_logic_hash(actual),PREVIOUS_LOGIC_HASH)

    def test_unknown_changes_are_not_aliased(self):
        self.assertEqual(compatible_logic_hash('unknown'),'unknown')
        self.assertEqual(compatible_rules_hash('unknown'),'unknown')

    def test_reviewed_delivery_description_keeps_existing_signatures(self):
        self.assertEqual(compatible_rules_hash('595ce27b53d9baea14aba26b8e9d0f72be56f95fab64e479140b753a81fdaaa1'),
                         'a05050e77c239383aad6b43f170293d2b010bbd27c3381af25248b4077115305')


if __name__=='__main__':unittest.main()
