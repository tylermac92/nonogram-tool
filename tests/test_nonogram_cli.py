"""Tests for the unified `nonogram` dispatcher: nonogram_cli.py."""

import unittest

from nonogram_tool.nonogram_cli import main


class TestDispatcher(unittest.TestCase):
    def test_no_args_prints_usage_and_exits_nonzero(self):
        self.assertEqual(main(["nonogram"]), 1)

    def test_help_flag_prints_usage_and_exits_zero(self):
        self.assertEqual(main(["nonogram", "--help"]), 0)
        self.assertEqual(main(["nonogram", "-h"]), 0)

    def test_unknown_subcommand_exits_nonzero(self):
        self.assertEqual(main(["nonogram", "bogus"]), 1)

    def test_overlap_subcommand_dispatches(self):
        self.assertEqual(main(["nonogram", "overlap", "5", "3"]), 0)

    def test_overlap_subcommand_propagates_failure_exit_code(self):
        # 8 > line length 5 - overlap's own main() returns 1 for this.
        self.assertEqual(main(["nonogram", "overlap", "5", "8"]), 1)

    def test_web_subcommand_dispatches_without_extras(self):
        # nonogram_web has no third-party dependency, so this should
        # import and run its usage path with no library id given.
        self.assertEqual(main(["nonogram", "web"]), 1)


if __name__ == "__main__":
    unittest.main()
