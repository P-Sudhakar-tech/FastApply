from ._turboply import dummy_add
from . import accessor  # noqa: F401  (registers the .turboply pandas accessors)

__version__ = "0.1.0"
__all__ = ["dummy_add", "__version__"]
