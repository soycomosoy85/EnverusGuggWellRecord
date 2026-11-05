import unittest
from WellConstraintAttributes import apply


class ConstraintAttributeTests(unittest.TestCase):
    def test_status_is_independent_of_constraint_flag(self):
        lookup={'PRODUCING':'PDP','PERMITTED':'PERMIT','DRILLING':'WIP','ABANDONED':'OTHER'}
        for status,expected in lookup.items():
            for trajectory in ['HORIZONTAL','DIRECTIONAL','VERTICAL','UNDETERMINED',None,'DEVIATED']:
                with self.subTest(status=status,trajectory=trajectory):
                    original=dict(EnvStatus=status,Trajectory=trajectory,WellConstr='Y')
                    result=apply(original,lookup)
                    self.assertEqual(result['WelCnsStat'],expected)
                    self.assertEqual(result['WellConstr'],'Y' if trajectory in ['HORIZONTAL','DIRECTIONAL'] else 'N')
                    self.assertEqual(original['WellConstr'],'Y')

    def test_never_upgrades_n_or_invents_unmapped_status(self):
        result=apply(dict(EnvStatus='UNLISTED',Trajectory='horizontal',WellConstr='N'),{'PRODUCING':'PDP'})
        self.assertEqual(result['WellConstr'],'N');self.assertIsNone(result['WelCnsStat'])
        self.assertIsNone(apply(dict(EnvStatus=None),{'PRODUCING':'PDP'})['WelCnsStat'])
        self.assertEqual(apply(dict(EnvStatus=' producing ',Trajectory=' directional ',WellConstr='Y'),{'PRODUCING':'PDP'})['WelCnsStat'],'PDP')


if __name__=='__main__':unittest.main()
