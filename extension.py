"""Vis entrypoint. The contract lives in vis_lang_interface."""

import blockether.vis.extension as vis

vis.register_extension(
    vis.Extension(
        name="vis-lang-interface",
        description="The shared contract for Vis language extensions.",
        version="2.1.0",
    )
)
