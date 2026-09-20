"""Vis entrypoint. The contract and the tools live in vis_lang_interface."""

import blockether.vis.extension as vis

from vis_lang_interface import presentation
from vis_lang_interface.tools import DataTools

DataTools.check = vis.method(
    activity=presentation.activity(
        "Check data files",
        lambda result: presentation.lint_presentation("Check data files", result),
        show_start=False,
    )
)(DataTools.check)

DataTools.format = vis.method(
    tag="mutation",
    activity=presentation.activity(
        "Format JSON",
        lambda result: presentation.format_presentation("Format JSON", result),
        show_start=False,
    ),
)(DataTools.format)

vis.register_extension(
    vis.Extension(
        name="vis-lang-interface",
        description="The shared contract for Vis language extensions, with exact JSON and TOML checks.",
        version="1.0.1",
        alias="data",
        symbols=[vis.Symbol(DataTools(), name="data")],
    )
)
