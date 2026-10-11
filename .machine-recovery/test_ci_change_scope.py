import importlib.util
from pathlib import Path
import unittest
source = Path(__file__).with_name("ci_change_scope.py")
spec = importlib.util.spec_from_file_location("scope", source)
module = importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name] = module
spec.loader.exec_module(module)
class ScopeContract(unittest.TestCase):
    def test_conservative_paths(self):
        self.assertTrue(module.is_docs_only(["README.md"]))
        for paths in [[], ["src/main.py"], ["docs/schema.json"], [".github/workflows/ci.yml"], ["README.md", "test.py"]]:
            self.assertFalse(module.is_docs_only(paths))
if __name__ == "__main__": unittest.main()
