from __future__ import annotations

import pytest

from coding613.application.resources import resource_profile


def test_standard_profile_allocates_sixteen_thousand_output_tokens() -> None:
    profile = resource_profile("standard", configured_max_output_tokens=200_000)

    assert profile.name == "standard"
    assert profile.max_output_tokens == 16_384


def test_complex_profile_allocates_128k_output_tokens() -> None:
    profile = resource_profile("complex", configured_max_output_tokens=200_000)

    assert profile.name == "complex"
    assert profile.max_output_tokens == 128_000


def test_simple_profile_is_no_longer_supported() -> None:
    with pytest.raises(ValueError, match="standard or complex"):
        resource_profile("simple", configured_max_output_tokens=200_000)
