# -*- coding: utf-8 -*-
"""
test_sprinkler_sizing.py - Automated Unit Test for Sprinkler Hydraulic Pipe Sizing
Validates compliance with TCVN 7336:2021 & NFPA 13.
"""
import unittest
import sys
import os

# Add lib/py to sys.path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(root_dir, "lib"))

# Mock pyrevit DB if not in Revit environment
import types
if "pyrevit" not in sys.modules:
    mock_pyrevit = types.ModuleType("pyrevit")
    mock_pyrevit.DB = types.ModuleType("DB")
    mock_pyrevit.revit = types.ModuleType("revit")
    mock_pyrevit.script = types.ModuleType("script")
    sys.modules["pyrevit"] = mock_pyrevit
if "Autodesk" not in sys.modules:
    mock_ad = types.ModuleType("Autodesk")
    mock_ad.Revit = types.ModuleType("Revit")
    mock_ad.Revit.DB = types.ModuleType("DB")
    mock_ad.Revit.DB.Transaction = types.SimpleNamespace
    mock_ad.Revit.DB.TransactionGroup = types.SimpleNamespace
    sys.modules["Autodesk"] = mock_ad
    sys.modules["Autodesk.Revit"] = mock_ad.Revit
    sys.modules["Autodesk.Revit.DB"] = mock_ad.Revit.DB

from py.sprinkler_engine import get_dn_for_head_count, SIZING_STANDARDS, mm_to_ft, ft_to_mm


class TestSprinklerHydraulicSizing(unittest.TestCase):

    def test_tcvn_7336_2021(self):
        """Validates stepped pipe sizing per TCVN 7336:2021 (Vietnam Standard)"""
        std = "TCVN 7336:2021 (Vietnam Standard)"
        
        # 1 to 2 heads -> DN25 (1")
        self.assertEqual(get_dn_for_head_count(1, std), 25)
        self.assertEqual(get_dn_for_head_count(2, std), 25)

        # 3 heads -> DN32 (1-1/4")
        self.assertEqual(get_dn_for_head_count(3, std), 32)

        # 4 to 5 heads -> DN40 (1-1/2")
        self.assertEqual(get_dn_for_head_count(4, std), 40)
        self.assertEqual(get_dn_for_head_count(5, std), 40)

        # 6 to 10 heads -> DN50 (2")
        self.assertEqual(get_dn_for_head_count(6, std), 50)
        self.assertEqual(get_dn_for_head_count(10, std), 50)

        # 11 to 20 heads -> DN65 (2-1/2")
        self.assertEqual(get_dn_for_head_count(11, std), 65)
        self.assertEqual(get_dn_for_head_count(20, std), 65)

        # 21 to 40 heads -> DN80 (3")
        self.assertEqual(get_dn_for_head_count(21, std), 80)
        self.assertEqual(get_dn_for_head_count(40, std), 80)

        # > 40 heads -> DN100 (4")
        self.assertEqual(get_dn_for_head_count(41, std), 100)
        self.assertEqual(get_dn_for_head_count(100, std), 100)

    def test_nfpa_13_light_hazard(self):
        """Validates stepped pipe sizing per NFPA 13 Light Hazard"""
        std = "NFPA 13 - Light Hazard (Offices / Schools)"
        
        self.assertEqual(get_dn_for_head_count(1, std), 25)
        self.assertEqual(get_dn_for_head_count(2, std), 25)
        self.assertEqual(get_dn_for_head_count(3, std), 32)
        self.assertEqual(get_dn_for_head_count(5, std), 40)
        self.assertEqual(get_dn_for_head_count(10, std), 50)
        self.assertEqual(get_dn_for_head_count(30, std), 65)
        self.assertEqual(get_dn_for_head_count(60, std), 80)
        self.assertEqual(get_dn_for_head_count(61, std), 100)

    def test_nfpa_13_ordinary_hazard(self):
        """Validates stepped pipe sizing per NFPA 13 Ordinary Hazard"""
        std = "NFPA 13 - Ordinary Hazard (Commercial / Storage)"
        
        self.assertEqual(get_dn_for_head_count(1, std), 25)
        self.assertEqual(get_dn_for_head_count(2, std), 25)
        self.assertEqual(get_dn_for_head_count(3, std), 32)
        self.assertEqual(get_dn_for_head_count(5, std), 40)
        self.assertEqual(get_dn_for_head_count(10, std), 50)
        self.assertEqual(get_dn_for_head_count(20, std), 65)
        self.assertEqual(get_dn_for_head_count(40, std), 80)
        self.assertEqual(get_dn_for_head_count(41, std), 100)

    def test_unit_conversions(self):
        """Validates metric to imperial unit conversions"""
        self.assertAlmostEqual(mm_to_ft(304.8), 1.0, places=4)
        self.assertAlmostEqual(ft_to_mm(1.0), 304.8, places=4)
        self.assertAlmostEqual(mm_to_ft(25.4), 1.0 / 12.0, places=4)


if __name__ == "__main__":
    unittest.main()
