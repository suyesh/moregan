"""Small, reproducible Python tasks shipped with the benchmark runner."""

from textwrap import dedent, indent


def _task(task_id, category, request, acceptance, source, checks):
    return {
        "id": task_id,
        "category": category,
        "request": request,
        "acceptance_criteria": acceptance,
        "files": {"app.py": dedent(source).lstrip()},
        "verification": (
            "import sys\nimport unittest\n"
            "sys.path.insert(0, sys.argv.pop(1))\n"
            "import app\n\nclass AcceptanceTests(unittest.TestCase):\n"
            + indent(dedent(checks).strip(), "    ") + "\n"
            + "\nif __name__ == '__main__':\n    unittest.main()\n"
        ),
    }


DEFAULT_BENCHMARK_TASKS = [
    _task(
        "bug-fix-null-response", "bug_fix",
        "Fix names(payload) in app.py to accept null responses and missing items.",
        ["None or missing items returns [].", "Valid item names preserve order.", "Do not mutate the input."],
        """
        def names(payload):
            return [item['name'] for item in payload['items']]
        """,
        """
        def test_null_and_missing(self):
            for value in (None, {}, {'items': None}, {'items': []}):
                self.assertEqual(app.names(value), [])
        def test_valid_payload(self):
            data = {'items': [{'name': 'A'}, {'name': 'B'}]}
            self.assertEqual(app.names(data), ['A', 'B'])
            self.assertEqual(data, {'items': [{'name': 'A'}, {'name': 'B'}]})
        """,
    ),
    _task(
        "feature-pagination", "feature",
        "Implement paginate(items, page, size) in app.py with one-based pages.",
        ["Return a list slice without mutating items.", "Out-of-range pages return [].",
         "Nonpositive page or size raises ValueError."],
        """
        def paginate(items, page, size):
            raise NotImplementedError
        """,
        """
        def test_pages(self):
            data = list(range(7))
            self.assertEqual(app.paginate(data, 1, 3), [0, 1, 2])
            self.assertEqual(app.paginate(data, 3, 3), [6])
            self.assertEqual(app.paginate(data, 4, 3), [])
            self.assertEqual(app.paginate([], 1, 2), [])
            self.assertEqual(data, list(range(7)))
        def test_invalid(self):
            for page, size in ((0, 2), (-1, 2), (1, 0), (1, -2)):
                with self.assertRaises(ValueError):
                    app.paginate([1], page, size)
        """,
    ),
    _task(
        "refactor-deduplication", "refactor",
        "Refactor unique(items) in app.py to remove the set construction and support unhashable items.",
        ["Preserve first-occurrence order using equality.", "Support dicts, lists, and generators.",
         "Leave inputs unchanged."],
        """
        def unique(items):
            return list(set(items))
        """,
        """
        def test_order(self):
            self.assertEqual(app.unique([3, 1, 3, 2, 1]), [3, 1, 2])
            self.assertEqual(app.unique(x for x in [2, 1, 2]), [2, 1])
        def test_unhashable(self):
            data = [{'a': 1}, [2], {'a': 1}, [2]]
            self.assertEqual(app.unique(data), [{'a': 1}, [2]])
            self.assertEqual(len(data), 4)
        """,
    ),
    _task(
        "security-path-traversal", "security",
        "Fix resolve_asset(root, name) in app.py to prevent path traversal.",
        ["Return a resolved Path inside root for valid names.", "Reject absolute paths and root itself.",
         "Reject paths or symlinks escaping root with ValueError."],
        """
        from pathlib import Path

        def resolve_asset(root, name):
            return Path(root) / name
        """,
        """
        def test_paths(self):
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'assets'
                root.mkdir()
                self.assertEqual(app.resolve_asset(root, 'a.txt'), (root / 'a.txt').resolve())
                for name in ('../secret', '.', str(Path(directory).resolve())):
                    with self.assertRaises(ValueError):
                        app.resolve_asset(root, name)
                try:
                    (root / 'escape').symlink_to(Path(directory), target_is_directory=True)
                except (OSError, NotImplementedError):
                    return
                with self.assertRaises(ValueError):
                    app.resolve_asset(root, 'escape/secret')
        """,
    ),
    _task(
        "migration-display-name", "migration",
        "Implement migrate(connection) in app.py for an existing SQLite users table.",
        ["Add nullable TEXT display_name without losing rows.", "Running migration twice is safe.",
         "Preserve existing display_name values."],
        """
        def migrate(connection):
            pass
        """,
        """
        def test_migration(self):
            import sqlite3
            with sqlite3.connect(':memory:') as connection:
                connection.execute('CREATE TABLE users (id INTEGER PRIMARY KEY)')
                connection.execute('INSERT INTO users VALUES (1)')
                app.migrate(connection)
                self.assertEqual(connection.execute('SELECT id, display_name FROM users').fetchall(), [(1, None)])
                connection.execute("UPDATE users SET display_name = 'Ada' WHERE id = 1")
                app.migrate(connection)
                self.assertEqual(connection.execute('SELECT display_name FROM users').fetchone(), ('Ada',))
        """,
    ),
    _task(
        "regression-expiry-boundary", "regression",
        "Fix is_expired(now, expires_at) in app.py at the exact expiry boundary.",
        ["Return True at or after expiry, False before expiry.", "None means no expiry.",
         "Accept integer and fractional timestamps."],
        """
        def is_expired(now, expires_at):
            return now > expires_at
        """,
        """
        def test_boundaries(self):
            self.assertIs(app.is_expired(10, 10), True)
            self.assertIs(app.is_expired(11, 10), True)
            self.assertIs(app.is_expired(9, 10), False)
            self.assertIs(app.is_expired(0, None), False)
            self.assertIs(app.is_expired(0.5, 0.5), True)
        """,
    ),
]
