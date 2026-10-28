import math
import random

import pytest

from data.geo import digipin


def test_reference_example_from_india_post():
    # Example documented in the India Post reference implementation.
    assert digipin.encode(13.11179621, 80.20264269) == "4T396F42L7"


def test_round_trip_stays_within_one_cell():
    rng = random.Random(7)
    for _ in range(500):
        lat, lon = rng.uniform(8, 35), rng.uniform(68, 97)
        clat, clon = digipin.decode(digipin.encode(lat, lon))
        # Level-10 cell is 36/4**10 degrees (~3.8 m) on a side.
        assert math.isclose(lat, clat, abs_tol=36 / 4 ** 10)
        assert math.isclose(lon, clon, abs_tol=36 / 4 ** 10)


def test_rejects_points_outside_india_box():
    with pytest.raises(ValueError):
        digipin.encode(51.5, -0.12)


def test_rejects_malformed_codes():
    for bad in ("4T396F42L", "4T396F42L0", "4T3-96F-42L7"):
        with pytest.raises(ValueError):
            digipin.decode(bad)
