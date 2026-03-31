from dataclasses import dataclass


@dataclass
class CityConfig:
    code: str              # "NYC", "CHI", etc.
    display_name: str      # "New York City"
    kalshi_series: str     # "KXHIGHNY"
    timezone: str          # "America/New_York"


CITIES: dict[str, CityConfig] = {
    # --- Original cities ---
    "NYC": CityConfig("NYC", "New York City", "KXHIGHNY", "America/New_York"),
    "CHI": CityConfig("CHI", "Chicago", "KXHIGHCHI", "America/Chicago"),
    "MIA": CityConfig("MIA", "Miami", "KXHIGHMIA", "America/New_York"),
    "LA":  CityConfig("LA",  "Los Angeles", "KXHIGHLAX", "America/Los_Angeles"),
    "DEN": CityConfig("DEN", "Denver", "KXHIGHDEN", "America/Denver"),

    # --- Expansion cities ---
    "AUS": CityConfig("AUS", "Austin", "KXHIGHAUS", "America/Chicago"),
    "ATL": CityConfig("ATL", "Atlanta", "KXHIGHTATL", "America/New_York"),
    "BOS": CityConfig("BOS", "Boston", "KXHIGHTBOS", "America/New_York"),
    "DAL": CityConfig("DAL", "Dallas", "KXHIGHTDAL", "America/Chicago"),
    "DC":  CityConfig("DC",  "Washington DC", "KXHIGHTDC", "America/New_York"),
    "HOU": CityConfig("HOU", "Houston", "KXHIGHTHOU", "America/Chicago"),
    "LV":  CityConfig("LV",  "Las Vegas", "KXHIGHTLV", "America/Los_Angeles"),
    "MIN": CityConfig("MIN", "Minneapolis", "KXHIGHTMIN", "America/Chicago"),
    "NOLA": CityConfig("NOLA", "New Orleans", "KXHIGHTNOLA", "America/Chicago"),
    "OKC": CityConfig("OKC", "Oklahoma City", "KXHIGHTOKC", "America/Chicago"),
    "PHX": CityConfig("PHX", "Phoenix", "KXHIGHTPHX", "America/Phoenix"),
    "PHIL": CityConfig("PHIL", "Philadelphia", "KXHIGHPHIL", "America/New_York"),
    "SATX": CityConfig("SATX", "San Antonio", "KXHIGHTSATX", "America/Chicago"),
    "SEA": CityConfig("SEA", "Seattle", "KXHIGHTSEA", "America/Los_Angeles"),
    "SFO": CityConfig("SFO", "San Francisco", "KXHIGHTSFO", "America/Los_Angeles"),
}


def get_active_cities(config) -> list[CityConfig]:
    if config.whitelisted_cities:
        whitelist = {c.upper() for c in config.whitelisted_cities}
        return [city for code, city in CITIES.items() if code in whitelist]
    blocked = {c.upper() for c in config.blocked_cities}
    return [city for code, city in CITIES.items() if code not in blocked]
