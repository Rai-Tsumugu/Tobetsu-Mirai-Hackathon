"""Run every quote test, including nested team-owned test modules."""
from pathlib import Path
import unittest

def main():
    root = Path(__file__).parent
    suite = unittest.TestSuite()
    for path in sorted(root.rglob('test_*.py')):
        if any(part in {'.venv', 'node_modules', '__pycache__'} for part in path.parts):
            continue
        relative = path.relative_to(root).with_suffix('')
        module_name = 'src.auto_repair_quote.' + '.'.join(relative.parts)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(module_name))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)

if __name__ == '__main__':
    main()
