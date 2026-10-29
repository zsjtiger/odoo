"""The external dependencies of the modules: the python packages, with their versions and markers."""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
import re
import typing

if typing.TYPE_CHECKING:
    pass


_logger = logging.getLogger('odoo.modules.module')


try:
    from packaging.requirements import InvalidRequirement, Requirement
except ImportError:
    class InvalidRequirement(Exception):  # type: ignore[no-redef]
        ...

    class Requirement:  # type: ignore[no-redef]
        def __init__(self, pydep):
            if not re.fullmatch(r'[\w\-]+', pydep):  # check that we have no versions or marker in pydep
                msg = f"Package `packaging` is required to parse `{pydep}` external dependency and is not installed"
                raise Exception(msg)
            self.marker = None
            self.specifier = None
            self.name = pydep


class MissingDependency(Exception):
    def __init__(self, msg_template: str, dependency: str):
        self.dependency = dependency
        super().__init__(msg_template.format(dependency=dependency))


def check_python_external_dependency(pydep: str) -> None:
    try:
        requirement = Requirement(pydep)
    except InvalidRequirement as e:
        msg = f"{pydep} is an invalid external dependency specification: {e}"
        raise ValueError(msg) from e
    if requirement.marker and not requirement.marker.evaluate():
        _logger.debug(
            "Ignored external dependency %s because environment markers do not match",
            pydep
        )
        return
    try:
        version = importlib.metadata.version(requirement.name)
    except importlib.metadata.PackageNotFoundError as e:
        try:
            # keep compatibility with module name but log a warning instead of info
            importlib.import_module(pydep)
            _logger.warning("python external dependency on '%s' does not appear to be a valid PyPI package. Using a PyPI package name is recommended.", pydep)
            return
        except ImportError:
            pass
        msg = "External dependency {dependency!r} not installed: %s" % (e,)
        raise MissingDependency(msg, pydep) from e
    if requirement.specifier and not requirement.specifier.contains(version):
        msg = f"External dependency version mismatch: {{dependency}} (installed: {version})"
        raise MissingDependency(msg, pydep)
