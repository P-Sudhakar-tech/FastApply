from importlib.metadata import version as _version

from . import accessor  # noqa: F401  (registers the .turbofastapply pandas accessors)

# Read from installed package metadata rather than hardcoding a literal --
# the release workflow overwrites Cargo.toml/pyproject.toml's version from
# the git tag at build time (see .github/workflows/release.yml), but never
# touches this file, so a hardcoded string here would silently go stale on
# every release after the first.
__version__ = _version("turbofastapply")
__all__ = ["__version__"]
