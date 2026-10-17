import datetime
import math


def sun_position(latitude, longitude, when):
    """Return (azimuth, elevation) in degrees; azimuth is clockwise from true north."""
    if when.tzinfo is None:
        raise ValueError("when must be timezone-aware")
    days = when.timestamp() / 86400.0 + 2440587.5 - 2451545.0
    mean_longitude = (280.460 + 0.9856474 * days) % 360
    anomaly = math.radians((357.528 + 0.9856003 * days) % 360)
    ecliptic_longitude = math.radians(
        mean_longitude + 1.915 * math.sin(anomaly) + 0.020 * math.sin(2 * anomaly)
    )
    obliquity = math.radians(23.439 - 0.0000004 * days)
    right_ascension = math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_longitude), math.cos(ecliptic_longitude)
    )
    declination = math.asin(math.sin(obliquity) * math.sin(ecliptic_longitude))
    sidereal = (280.46061837 + 360.98564736629 * days + longitude) % 360
    hour_angle = math.radians(sidereal) - right_ascension
    lat = math.radians(latitude)
    elevation = math.asin(
        math.sin(lat) * math.sin(declination)
        + math.cos(lat) * math.cos(declination) * math.cos(hour_angle)
    )
    azimuth = math.atan2(
        -math.cos(declination) * math.sin(hour_angle),
        math.sin(declination) * math.cos(lat)
        - math.cos(declination) * math.sin(lat) * math.cos(hour_angle),
    )
    return math.degrees(azimuth) % 360, math.degrees(elevation)


def sun_on_facing(latitude, longitude, facing_degrees, when, min_elevation=8.0, half_angle=80.0):
    """True when the sun is high enough and within half_angle of a wall's outward normal."""
    azimuth, elevation = sun_position(latitude, longitude, when)
    if elevation < min_elevation:
        return False
    difference = abs((azimuth - facing_degrees + 180) % 360 - 180)
    return difference < half_angle
