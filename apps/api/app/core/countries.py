"""
Server-authoritative country resolution from a WhatsApp id / phone number.

The WhatsApp `wa_id` is the full international number without a '+', e.g.
"254717905405". We resolve the dialing prefix to a country by LONGEST-PREFIX
match (so "1-684" American Samoa wins over "1" USA/Canada). This mirrors the
table the n8n "countrycodes" node uses, but runs on the server so every
customer gets a country regardless of whether the n8n enrichment call landed.

Used at message/user upsert time and by the CRM backfill migration.
"""
from __future__ import annotations

# (dialing-prefix-digits, country name, ISO-3166 alpha-2)
_COUNTRY_TABLE: list[tuple[str, str, str]] = [
    ("93", "Afghanistan", "AF"),
    ("355", "Albania", "AL"),
    ("213", "Algeria", "DZ"),
    ("1684", "American Samoa", "AS"),
    ("376", "Andorra", "AD"),
    ("244", "Angola", "AO"),
    ("1264", "Anguilla", "AI"),
    ("672", "Antarctica", "AQ"),
    ("1268", "Antigua and Barbuda", "AG"),
    ("54", "Argentina", "AR"),
    ("374", "Armenia", "AM"),
    ("297", "Aruba", "AW"),
    ("61", "Australia", "AU"),
    ("43", "Austria", "AT"),
    ("994", "Azerbaijan", "AZ"),
    ("1242", "Bahamas", "BS"),
    ("973", "Bahrain", "BH"),
    ("880", "Bangladesh", "BD"),
    ("1246", "Barbados", "BB"),
    ("375", "Belarus", "BY"),
    ("32", "Belgium", "BE"),
    ("501", "Belize", "BZ"),
    ("229", "Benin", "BJ"),
    ("1441", "Bermuda", "BM"),
    ("975", "Bhutan", "BT"),
    ("591", "Bolivia", "BO"),
    ("387", "Bosnia and Herzegovina", "BA"),
    ("267", "Botswana", "BW"),
    ("55", "Brazil", "BR"),
    ("246", "British Indian Ocean Territory", "IO"),
    ("1284", "British Virgin Islands", "VG"),
    ("673", "Brunei", "BN"),
    ("359", "Bulgaria", "BG"),
    ("226", "Burkina Faso", "BF"),
    ("257", "Burundi", "BI"),
    ("855", "Cambodia", "KH"),
    ("237", "Cameroon", "CM"),
    ("1", "Canada", "CA"),
    ("238", "Cape Verde", "CV"),
    ("1345", "Cayman Islands", "KY"),
    ("236", "Central African Republic", "CF"),
    ("235", "Chad", "TD"),
    ("56", "Chile", "CL"),
    ("86", "China", "CN"),
    ("61", "Christmas Island", "CX"),
    ("61", "Cocos Islands", "CC"),
    ("57", "Colombia", "CO"),
    ("269", "Comoros", "KM"),
    ("682", "Cook Islands", "CK"),
    ("506", "Costa Rica", "CR"),
    ("385", "Croatia", "HR"),
    ("53", "Cuba", "CU"),
    ("599", "Curacao", "CW"),
    ("357", "Cyprus", "CY"),
    ("420", "Czech Republic", "CZ"),
    ("243", "Democratic Republic of the Congo", "CD"),
    ("45", "Denmark", "DK"),
    ("253", "Djibouti", "DJ"),
    ("1767", "Dominica", "DM"),
    ("1809", "Dominican Republic", "DO"),
    ("670", "East Timor", "TL"),
    ("593", "Ecuador", "EC"),
    ("20", "Egypt", "EG"),
    ("503", "El Salvador", "SV"),
    ("240", "Equatorial Guinea", "GQ"),
    ("291", "Eritrea", "ER"),
    ("372", "Estonia", "EE"),
    ("251", "Ethiopia", "ET"),
    ("500", "Falkland Islands", "FK"),
    ("298", "Faroe Islands", "FO"),
    ("679", "Fiji", "FJ"),
    ("358", "Finland", "FI"),
    ("33", "France", "FR"),
    ("689", "French Polynesia", "PF"),
    ("241", "Gabon", "GA"),
    ("220", "Gambia", "GM"),
    ("995", "Georgia", "GE"),
    ("49", "Germany", "DE"),
    ("233", "Ghana", "GH"),
    ("350", "Gibraltar", "GI"),
    ("30", "Greece", "GR"),
    ("299", "Greenland", "GL"),
    ("1473", "Grenada", "GD"),
    ("1671", "Guam", "GU"),
    ("502", "Guatemala", "GT"),
    ("441481", "Guernsey", "GG"),
    ("224", "Guinea", "GN"),
    ("245", "Guinea-Bissau", "GW"),
    ("592", "Guyana", "GY"),
    ("509", "Haiti", "HT"),
    ("504", "Honduras", "HN"),
    ("852", "Hong Kong", "HK"),
    ("36", "Hungary", "HU"),
    ("354", "Iceland", "IS"),
    ("91", "India", "IN"),
    ("62", "Indonesia", "ID"),
    ("98", "Iran", "IR"),
    ("964", "Iraq", "IQ"),
    ("353", "Ireland", "IE"),
    ("441624", "Isle of Man", "IM"),
    ("972", "Israel", "IL"),
    ("39", "Italy", "IT"),
    ("225", "Ivory Coast", "CI"),
    ("1876", "Jamaica", "JM"),
    ("81", "Japan", "JP"),
    ("441534", "Jersey", "JE"),
    ("962", "Jordan", "JO"),
    ("7", "Kazakhstan", "KZ"),
    ("254", "Kenya", "KE"),
    ("686", "Kiribati", "KI"),
    ("383", "Kosovo", "XK"),
    ("965", "Kuwait", "KW"),
    ("996", "Kyrgyzstan", "KG"),
    ("856", "Laos", "LA"),
    ("371", "Latvia", "LV"),
    ("961", "Lebanon", "LB"),
    ("266", "Lesotho", "LS"),
    ("231", "Liberia", "LR"),
    ("218", "Libya", "LY"),
    ("423", "Liechtenstein", "LI"),
    ("370", "Lithuania", "LT"),
    ("352", "Luxembourg", "LU"),
    ("853", "Macao", "MO"),
    ("389", "Macedonia", "MK"),
    ("261", "Madagascar", "MG"),
    ("265", "Malawi", "MW"),
    ("60", "Malaysia", "MY"),
    ("960", "Maldives", "MV"),
    ("223", "Mali", "ML"),
    ("356", "Malta", "MT"),
    ("692", "Marshall Islands", "MH"),
    ("222", "Mauritania", "MR"),
    ("230", "Mauritius", "MU"),
    ("262", "Mayotte", "YT"),
    ("52", "Mexico", "MX"),
    ("691", "Micronesia", "FM"),
    ("373", "Moldova", "MD"),
    ("377", "Monaco", "MC"),
    ("976", "Mongolia", "MN"),
    ("382", "Montenegro", "ME"),
    ("1664", "Montserrat", "MS"),
    ("212", "Morocco", "MA"),
    ("258", "Mozambique", "MZ"),
    ("95", "Myanmar", "MM"),
    ("264", "Namibia", "NA"),
    ("674", "Nauru", "NR"),
    ("977", "Nepal", "NP"),
    ("31", "Netherlands", "NL"),
    ("599", "Netherlands Antilles", "AN"),
    ("687", "New Caledonia", "NC"),
    ("64", "New Zealand", "NZ"),
    ("505", "Nicaragua", "NI"),
    ("227", "Niger", "NE"),
    ("234", "Nigeria", "NG"),
    ("683", "Niue", "NU"),
    ("850", "North Korea", "KP"),
    ("1670", "Northern Mariana Islands", "MP"),
    ("47", "Norway", "NO"),
    ("968", "Oman", "OM"),
    ("92", "Pakistan", "PK"),
    ("680", "Palau", "PW"),
    ("970", "Palestine", "PS"),
    ("507", "Panama", "PA"),
    ("675", "Papua New Guinea", "PG"),
    ("595", "Paraguay", "PY"),
    ("51", "Peru", "PE"),
    ("63", "Philippines", "PH"),
    ("64", "Pitcairn", "PN"),
    ("48", "Poland", "PL"),
    ("351", "Portugal", "PT"),
    ("1787", "Puerto Rico", "PR"),
    ("974", "Qatar", "QA"),
    ("242", "Republic of the Congo", "CG"),
    ("262", "Reunion", "RE"),
    ("40", "Romania", "RO"),
    ("7", "Russia", "RU"),
    ("250", "Rwanda", "RW"),
    ("590", "Saint Barthelemy", "BL"),
    ("290", "Saint Helena", "SH"),
    ("1869", "Saint Kitts and Nevis", "KN"),
    ("1758", "Saint Lucia", "LC"),
    ("590", "Saint Martin", "MF"),
    ("508", "Saint Pierre and Miquelon", "PM"),
    ("1784", "Saint Vincent and the Grenadines", "VC"),
    ("685", "Samoa", "WS"),
    ("378", "San Marino", "SM"),
    ("239", "Sao Tome and Principe", "ST"),
    ("966", "Saudi Arabia", "SA"),
    ("221", "Senegal", "SN"),
    ("381", "Serbia", "RS"),
    ("248", "Seychelles", "SC"),
    ("232", "Sierra Leone", "SL"),
    ("65", "Singapore", "SG"),
    ("1721", "Sint Maarten", "SX"),
    ("421", "Slovakia", "SK"),
    ("386", "Slovenia", "SI"),
    ("677", "Solomon Islands", "SB"),
    ("252", "Somalia", "SO"),
    ("27", "South Africa", "ZA"),
    ("82", "South Korea", "KR"),
    ("211", "South Sudan", "SS"),
    ("34", "Spain", "ES"),
    ("94", "Sri Lanka", "LK"),
    ("249", "Sudan", "SD"),
    ("597", "Suriname", "SR"),
    ("47", "Svalbard and Jan Mayen", "SJ"),
    ("268", "Swaziland", "SZ"),
    ("46", "Sweden", "SE"),
    ("41", "Switzerland", "CH"),
    ("963", "Syria", "SY"),
    ("886", "Taiwan", "TW"),
    ("992", "Tajikistan", "TJ"),
    ("255", "Tanzania", "TZ"),
    ("66", "Thailand", "TH"),
    ("228", "Togo", "TG"),
    ("690", "Tokelau", "TK"),
    ("676", "Tonga", "TO"),
    ("1868", "Trinidad and Tobago", "TT"),
    ("216", "Tunisia", "TN"),
    ("90", "Turkey", "TR"),
    ("993", "Turkmenistan", "TM"),
    ("1649", "Turks and Caicos Islands", "TC"),
    ("688", "Tuvalu", "TV"),
    ("1340", "U.S. Virgin Islands", "VI"),
    ("256", "Uganda", "UG"),
    ("380", "Ukraine", "UA"),
    ("971", "United Arab Emirates", "AE"),
    ("44", "United Kingdom", "GB"),
    ("1", "United States", "US"),
    ("598", "Uruguay", "UY"),
    ("998", "Uzbekistan", "UZ"),
    ("678", "Vanuatu", "VU"),
    ("379", "Vatican", "VA"),
    ("58", "Venezuela", "VE"),
    ("84", "Vietnam", "VN"),
    ("681", "Wallis and Futuna", "WF"),
    ("212", "Western Sahara", "EH"),
    ("967", "Yemen", "YE"),
    ("260", "Zambia", "ZM"),
    ("263", "Zimbabwe", "ZW"),
]

# Pre-sort by descending prefix length so the first match is the most specific.
_SORTED = sorted(_COUNTRY_TABLE, key=lambda r: len(r[0]), reverse=True)


def flag_url_for(iso: str | None) -> str | None:
    """A CDN SVG flag for an ISO alpha-2 code (lower-cased)."""
    if not iso:
        return None
    return f"https://flagcdn.com/{iso.lower()}.svg"


def resolve_country(wa_id_or_phone: str | None) -> dict:
    """Resolve {country, country_iso, flag_url} from a wa_id/phone.

    Returns a dict with None values when nothing matches (never raises), so
    callers can spread it unconditionally.
    """
    empty = {"country": None, "country_iso": None, "flag_url": None, "code": None}
    if not wa_id_or_phone:
        return empty
    digits = "".join(ch for ch in str(wa_id_or_phone) if ch.isdigit())
    if not digits:
        return empty
    for prefix, name, iso in _SORTED:
        if digits.startswith(prefix):
            return {"country": name, "country_iso": iso, "flag_url": flag_url_for(iso), "code": prefix}
    return empty


def iso_from_text(text: str | None) -> str | None:
    """Best-effort ISO country from free text (e.g. a captured location like
    'Somerset East, Eastern Cape, South Africa'). Longest country name wins so
    'South Sudan' never matches plain 'Sudan'. None when nothing matches."""
    t = (text or "").lower()
    if not t:
        return None
    best: tuple[int, str] | None = None
    for _prefix, name, iso in _COUNTRY_TABLE:
        n = name.lower()
        if n in t and (best is None or len(n) > best[0]):
            best = (len(n), iso)
    return best[1] if best else None


def name_for_iso(iso: str | None) -> str | None:
    """Country display name for an ISO alpha-2 code ('UG' → 'Uganda')."""
    if not iso:
        return None
    up = iso.upper()
    for _code, name, code2 in _COUNTRY_TABLE:
        if code2 == up:
            return name
    return None


def iso_from_locale(locale: str | None) -> str | None:
    """Country ISO from a Meta profile locale ('sw_KE' → 'KE', 'en_ZA' → 'ZA').
    Validated against the country table; None for bare-language locales ('en')."""
    if not locale or "_" not in str(locale):
        return None
    suffix = str(locale).rsplit("_", 1)[-1].upper()
    return suffix if name_for_iso(suffix) else None


# Country ISO → its official currency (ISO 4217). A stable geographic fact — NOT
# business config: it says "a Zambian's money is ZMW", independent of whether the
# hub prices anything in ZMW yet. The catalog uses this to pick a customer's
# currency, then shows it only when the hub actually has that price (else USD).
# Covers Bethany House's markets (Africa + common diaspora); everyone else → USD.
_CURRENCY_BY_ISO = {
    "KE": "KES", "ZM": "ZMW", "UG": "UGX", "TZ": "TZS", "ZA": "ZAR",
    "NG": "NGN", "GH": "GHS", "RW": "RWF", "MW": "MWK", "ZW": "USD",
    # SS/CD/BI/SL: currencies too volatile/thin to fallback-rate reliably, so we
    # quote USD (as with ZW/LR) until the hub prices them or a rate is configured.
    "SS": "USD", "ET": "ETB", "CD": "USD", "CM": "XAF", "CI": "XOF",
    "BI": "USD", "SL": "USD", "LR": "USD", "BW": "BWP", "NA": "NAD",
    "GB": "GBP", "US": "USD", "CA": "CAD", "AU": "AUD",
}
# Currencies the EU / eurozone diaspora may want; kept for future hub pricing.
for _iso in ("DE", "FR", "IT", "ES", "NL", "IE", "PT", "BE"):
    _CURRENCY_BY_ISO[_iso] = "EUR"


def currency_for_country(iso: str | None) -> str:
    """The customer's own currency for a country ISO — USD for anywhere we don't
    map (the safe, universally-accepted default)."""
    return _CURRENCY_BY_ISO.get((iso or "").upper(), "USD")
