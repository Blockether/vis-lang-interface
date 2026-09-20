"""The tools the interface extension itself serves: JSON and TOML, no toolchain.

Every other language needs a compiler or a linter installed. JSON and TOML do
not: Python parses both, so these two tools work in any project, and they are
also the smallest complete example of the contract in `vis_lang_interface`.
"""

from __future__ import annotations

from typing import Annotated

from vis_lang_interface.data import SUFFIXES, check_files, format_files
from vis_lang_interface.project import source_files
from vis_lang_interface.results import FormatResult, LintResult


class DataTools:
    """Check JSON and TOML, and reformat JSON."""

    def check(
        self,
        paths: Annotated[list[str], "Files or directories to read."],
    ) -> LintResult:
        """Parse every JSON and TOML file under paths and report what fails.

        Reads the files and changes nothing. Raises ValueError when the paths
        hold no JSON or TOML file, and FileNotFoundError for a missing path.
        """
        files = source_files(paths, SUFFIXES)
        if not files:
            raise ValueError("no JSON or TOML file in the given paths")
        return check_files(files)

    def format(
        self,
        paths: Annotated[list[str], "JSON files or directories to reformat."],
        *,
        is_written: Annotated[bool, "Rewrite the files instead of reporting."] = False,
        indent: Annotated[int, "Spaces per nesting level."] = 2,
    ) -> FormatResult:
        """Reformat JSON with a fixed indent and a final newline.

        With is_written the files that differ are rewritten; otherwise nothing is
        written and the result lists what would change. Raises ValueError when a
        file does not parse or no JSON file is found.
        """
        files = source_files(paths, (".json",))
        if not files:
            raise ValueError("no JSON file in the given paths")
        return format_files(files, indent=indent, is_written=is_written)
