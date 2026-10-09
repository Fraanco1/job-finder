"""Geocoder tests. They need the GeoNames files (downloaded on first use, ~10 MB)."""

import os

import pytest

from jobfinder.geocode import geocode

pytestmark = pytest.mark.skipif(os.environ.get("JOBFINDER_OFFLINE") == "1", reason="needs GeoNames data")


@pytest.mark.parametrize("text,city,cc", [
    ("Boulder, CO", "Boulder", "US"),
    ("Munich, DE", "Munich", "DE"),
    ("Wilmington, DE", "Wilmington", "US"),
    ("Toronto, ON", "Toronto", "CA"),
    ("Cambridge, MA", "Cambridge", "US"),
    ("Cambridge, UK", "Cambridge", "GB"),
    ("Delft, Netherlands", "Delft", "NL"),
    ("Bariloche, Argentina", "San Carlos de Bariloche", "AR"),
    ("Göteborg, 40530, Box 711", "Gothenburg", "SE"),
])
def test_city(text, city, cc):
    loc = geocode(text)
    assert (loc.city, loc.country_code, loc.precision) == (city, cc, "city")
    assert loc.lat is not None


def test_remote_country_falls_back_to_country_point():
    loc = geocode("Remote - US")
    assert loc.remote and loc.country_code == "US" and loc.precision == "country"


def test_country_hint():
    loc = geocode("Córdoba", country_hint="Argentina")
    assert loc.country_code == "AR"
