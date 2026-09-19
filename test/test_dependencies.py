import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def requirement_entries(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


class DependencyLockContracts(unittest.TestCase):
    def test_runtime_dependency_range_has_a_frozen_compatible_lock(self):
        self.assertEqual(
            requirement_entries(ROOT / "requirements.txt"),
            ["websockets>=15,<16"],
        )
        self.assertEqual(
            requirement_entries(ROOT / "requirements.lock.txt"),
            ["websockets==15.0.1"],
        )


if __name__ == "__main__":
    unittest.main()
