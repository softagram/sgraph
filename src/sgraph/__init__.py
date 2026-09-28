from importlib.metadata import version, PackageNotFoundError

from sgraph.sgraph import SGraph
from sgraph.selement import SElement
from sgraph.exceptions import SElementMergedException, ModelNotFoundException
from sgraph.selementassociation import SElementAssociation
from sgraph.modelapi import ModelApi
from sgraph.metricsapi import MetricsApi

__all__ = [
    'SGraph',
    'SElement',
    'SElementMergedException',
    'ModelNotFoundException',
    'SElementAssociation',
    'ModelApi',
    'MetricsApi',
    '__version__',
]

try:
    __version__ = version("sgraph")
except PackageNotFoundError:
    __version__ = "unknown"
