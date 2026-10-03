import unittest

import calc


class TestCalc(unittest.TestCase):
    def test_add(self):
        self.assertEqual(calc.add(2, 3), 5)

    def test_sub(self):
        self.assertEqual(calc.sub(5, 3), 2)

    def test_mul(self):
        self.assertEqual(calc.mul(4, 3), 12)

    def test_div(self):
        self.assertEqual(calc.div(6, 3), 2)
        with self.assertRaises(ZeroDivisionError):
            calc.div(1, 0)


if __name__ == "__main__":
    unittest.main()
