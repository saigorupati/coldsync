from dataclasses import dataclass


@dataclass
class CityConfig:
    code: str              # "NYC", "CHI", etc.
    display_name: str      # "New York City"
    kalshi_series: str     # "KXHIGHNY"
    timezone: str          # "America/New_York"


CITIES: dict[str, CityConfig] = {
    "NYC": CityConfig("NYC", "New York City", "KXHIGHNY", "America/New_York"),
    "CHI": CityConfig("CHI", "Chicago", "KXHIGHCHI", "America/Chicago"),
    "MIA": CityConfig("MIA", "Miami", "KXHIGHMIA", "America/New_York"),
    "LA":  CityConfig("LA",  "Los Angeles", "KXHIGHLAX", "America/Los_Angeles"),
    "PHX": CityConfig("PHX", "Phoenix", "KXHIGHTPHX", "America/Phoenix"),
    "ATL": CityConfig("ATL", "Atlanta", "KXHIGHATL", "America/New_York"),
    "DFW": CityConfig("DFW", "Dallas", "KXHIGHDFW", "America/Chicago"),
    "HOU": CityConfig("HOU", "Houston", "KXHIGHHOU", "America/Chicago"),
    "DEN": CityConfig("DEN", "Denver", "KXHIGHDEN", "America/Denver"),
}


def get_active_cities(config) -> list[CityConfig]:
    if config.whitelisted_cities:
        whitelist = {c.upper() for c in config.whitelisted_cities}
        return [city for code, city in CITIES.items() if code in whitelist]
    blocked = {c.upper() for c in config.blocked_cities}
    return [city for code, city in CITIES.items() if code not in blocked]
