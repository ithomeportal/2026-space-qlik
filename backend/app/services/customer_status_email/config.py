"""The four PCA load-status e-mails, as data.

Source: ``CUSTOMER REPORT TEMPLATE.xlsx`` + ``schedules.png`` (request
2026-10-20). Lanes are bill-to ``CENTRATX`` picking up at ``CENTWATX``
(Central Texas Corrugated, WACO TX) and delivering to the listed McLeod
destination location codes.

⚠ The McLeod stop/location table is NOT mirrored in the datalake — no gold
table carries the destination ``location_id`` for these orders (CENTRATX has 0%
EDI coverage, so ``mcleod_gld_edi_stop`` does not help). A destination is
therefore matched on the consignee NAME the order carries
(``customer_view.location_name``), mapped once from each code. Every mapping
below was checked against 2026 CENTRATX orders; a renamed consignee falls out
of its report, which is why the sender logs every UNMATCHED active consignee
on each run instead of dropping it silently.

``REYNOSA`` in the template is a city, not a location code (every real code
is 8 characters: 4 name + 2 city + 2 state), so it matches by delivery city.
"""
from __future__ import annotations

from dataclasses import dataclass

BILL_TO = "CENTRATX"
# CENTWATX — Central Texas Corrugated, the only pickup on every lane.
ORIGIN_CITY = "WACO"
ORIGIN_STATE = "TX"
ORIGIN_TZ = "America/Chicago"

SEND_FROM = "mvazquez@unilinktransportation.com"  # Magaly Vazquez, Tracking & Tracing
T1OPS = "t1ops@unilinktransportation.com"

# 🛑 TEST ROUTING (request 2026-10-20): "No send nothing to any customer yet" —
# every e-mail goes to Jaime Anaya acting as the customer, From Magaly, CC
# t1ops, BCC dfrodriguez. Applied unless CUSTOMER_STATUS_EMAIL_LIVE is set,
# and ALWAYS for an admin's manual test send.
TEST_TO: tuple[str, ...] = ("janaya@unilinktransportation.com",)
TEST_CC: tuple[str, ...] = (T1OPS,)
TEST_BCC: tuple[str, ...] = ("dfrodriguez@unilinktransportation.com",)

# Zone names chosen for stability on older tzdata: Juárez has followed US
# Mountain time (≡ America/Denver) since 2022, Chihuahua city follows UTC-6
# without DST (≡ America/Mexico_City) since 2022 — the newer zone ids
# (America/Ciudad_Juarez) are missing from tzdata before 2022g.
TZ_CENTRAL_US = "America/Chicago"
TZ_MOUNTAIN_US = "America/Denver"
TZ_MX_CENTRAL = "America/Mexico_City"
TZ_MONTERREY = "America/Monterrey"
TZ_MATAMOROS = "America/Matamoros"


@dataclass(frozen=True)
class Destination:
    """One McLeod destination code, matched on consignee name OR delivery city."""

    code: str
    names: tuple[str, ...] = ()       # normalised (upper, single-spaced)
    city: str = ""                    # "REYNOSA, TM" — city rule when no name
    tz: str = TZ_CENTRAL_US           # the stop's local clock (McLeod stores local)


@dataclass(frozen=True)
class CustomerReport:
    key: str
    subject: str
    destinations: tuple[Destination, ...]
    send_hours: tuple[int, ...]       # CST hours, every day
    to: tuple[str, ...]               # the REAL customer list — used only when live
    cc: tuple[str, ...] = (T1OPS,)
    send_from: str = SEND_FROM


_PCA_TEAM = (
    "PSCWLSalesDept@packagingcorp.com",
    "FranchescaRico@packagingcorp.com",
    "ConstanzaMendoza@packagingcorp.com",
    "WendyCasas@packagingcorp.com",
    "AlexanderMoreno@packagingcorp.com",
)

REPORTS: tuple[CustomerReport, ...] = (
    CustomerReport(
        key="pca-donna",
        subject="DONNA REPORT",
        destinations=(Destination("PCADDOTX", ("PCA DONNA",)),),
        send_hours=(2, 7, 12, 15, 22),  # 3:00 PM — the only report not at 4 PM
        to=("fhernandez@packagingcorp.com", "MarinaOlivarez@packagingcorp.com"),
    ),
    CustomerReport(
        key="pca-laredo",
        subject="PCA / CTC REPORT - LAREDO",
        destinations=(
            Destination("ALDETLJA", ("ALDEX EMPAQUES DE MEXICO", "ALDEX EMPAQUES"), tz=TZ_MX_CENTRAL),
            Destination("ASCMAPNX", ("ASC MANUFACTURING",), tz=TZ_MONTERREY),
            Destination("BOXUCANX", ("BOX UP",), tz=TZ_MONTERREY),
            Destination("CORRSAJA", ("CORRUGADOS HEAVY BOX SAN ISIDRO",), tz=TZ_MX_CENTRAL),
            Destination("EMPASAN1", ("EMPAQUES CARMA",), tz=TZ_MONTERREY),
            # ⚠ Best match, not proven: the only ALT*/Tlajomulco consignee.
            Destination("ALTOSAJA", ("ALTA TRANSFORMACIONES",), tz=TZ_MX_CENTRAL),
            Destination("IECEMON1", ("IEC EMPAQUE",), tz=TZ_MONTERREY),
            Destination("INNOSANX", ("INNOVACION PACKING AUTOMOTORES",), tz=TZ_MONTERREY),
            Destination("NEFAZAJA", ("NEFAB",), tz=TZ_MX_CENTRAL),
            Destination("PARQTLJA", ("PARQUE ADVANCE AEROPUERTO/ ALPI CORR",), tz=TZ_MX_CENTRAL),
        ),
        send_hours=(2, 7, 12, 16, 22),
        to=_PCA_TEAM,
    ),
    CustomerReport(
        key="pca-el-paso",
        subject="PCA / CTC REPORT - EL PASO",
        destinations=(
            Destination("ABMAJUCI", ("AB MATERIAL SUPPLY",), tz=TZ_MOUNTAIN_US),
            Destination("DIGSJUCI", ("DIGSSA PACKAGING AND SUPPLY",), tz=TZ_MOUNTAIN_US),
            Destination("NEFAJUCH", ("NEFAB JUAREZ",), tz=TZ_MOUNTAIN_US),
            Destination("TECNCHCI", ("TECNO CORRUGADOS",), tz=TZ_MX_CENTRAL),
            Destination("PCAEELTX", ("PCA EL PASO",), tz=TZ_MOUNTAIN_US),
        ),
        send_hours=(2, 7, 12, 16, 22),
        to=_PCA_TEAM,
    ),
    CustomerReport(
        key="pca-reynosa",
        subject="PCA / CTC REPORT - REYNOSA",
        destinations=(
            Destination("REYNOSA", city="REYNOSA, TM", tz=TZ_MATAMOROS),
            Destination("REGIRITM", ("REGIO PAK",), tz=TZ_MATAMOROS),
            Destination("AGEBRETM", ("AGE BOX DE MEXICO",), tz=TZ_MATAMOROS),
            Destination("WOORRETM", ("WOORI - BO KWANG PRINTING S.A. DE C.V.",), tz=TZ_MATAMOROS),
        ),
        send_hours=(2, 7, 12, 16, 22),
        to=_PCA_TEAM,
    ),
)

REPORTS_BY_KEY: dict[str, CustomerReport] = {r.key: r for r in REPORTS}

# Every hour any report sends — the scheduler's CronTrigger fires on these.
SEND_HOURS: tuple[int, ...] = tuple(sorted({h for r in REPORTS for h in r.send_hours}))


def normalise(text: str | None) -> str:
    """Upper-case, trimmed, single-spaced — McLeod names drift in case/spacing."""
    return " ".join((text or "").upper().split())


def match_destination(
    report: CustomerReport, consignee: str | None, delivery_location: str | None
) -> Destination | None:
    """The destination of ``report`` this consignee belongs to, else None.

    A NAME match wins over a CITY rule, so a WOORI load is attributed to
    WOORRETM (its own code), never to the generic REYNOSA city rule.
    """
    name = normalise(consignee)
    for dest in report.destinations:
        if name and name in dest.names:
            return dest
    city = normalise(delivery_location)
    for dest in report.destinations:
        if dest.city and city == dest.city:
            return dest
    return None


def reports_due(hour: int) -> tuple[CustomerReport, ...]:
    """The reports scheduled for this CST hour."""
    return tuple(r for r in REPORTS if hour in r.send_hours)
