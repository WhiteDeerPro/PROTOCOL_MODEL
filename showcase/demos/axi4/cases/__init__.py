"""Theme-oriented AXI4 example catalog."""

from .exclusive_profile import exclusive_profile_cases
from .geometry import geometry_cases
from .lifecycle import lifecycle_cases
from .observation import observation_cases
from .ordering import ordering_cases


def build_example_cases():
    """Build the catalog in the same order used by the public coverage matrix."""

    return (
        *lifecycle_cases(),
        *geometry_cases(),
        *ordering_cases(),
        *observation_cases(),
        *exclusive_profile_cases(),
    )


__all__ = ["build_example_cases"]
