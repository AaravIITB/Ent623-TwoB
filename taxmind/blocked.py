"""Blocked credit red flags - Sec 17(5) CGST Act.

An invoice can match GSTR-2B perfectly and still carry ITC the law does not allow:
food on a hotel bill, car repairs, club fees, gifts. GSTR-2B only marks place-of-supply
and Sec 16(4) cases as 'ITC not available', so nothing on the portal catches these.

TwoB flags likely Sec 17(5) items FOR REVIEW. It never reverses ITC by itself,
because most blocks have exceptions (e.g. food bought by a caterer for resale, cars
bought by a car dealer, insurance an employer must provide by law).

Evidence used, strongest first:
  HSN / SAC code     e.g. SAC 99633x food serving, HSN 8703 motor cars
  ledger / expense head and item description in the books
  supplier name only (weakest - 'Possible')

The 57th GST Council (8 Oct 2026) recommended removing the blocks on outdoor catering, life/health
insurance, telecom towers, pipelines outside the factory, free samples and shelf-life expiry
write-offs. That needs a law amendment (no effective date yet), so it is NOT applied here.

Not covered (not visible on an invoice): (e) composition, (f) non-resident taxable persons - these
depend on the client's own registration - and (i) tax paid under Sec 74 up to FY 2023-24.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import DocType, Finding


@dataclass
class Rule:
    rid: str
    label: str
    section: str
    words: re.Pattern
    hsn: tuple = ()                     # HSN / SAC prefixes
    exceptions: str = ""                # when ITC is still allowed
    unless: re.Pattern | None = None    # text that rules this out (e.g. goods vehicles)
    maybe: re.Pattern | None = None     # vague ledger words that only justify 'Possible'
    goods: bool = False                 # bought goods: skipped when the books show they are for resale


def _w(*terms) -> re.Pattern:
    return re.compile(r"(?<![a-z])(" + "|".join(terms) + r")(?![a-z])", re.I)


RULES = [
    Rule("food", "Food and beverages / outdoor catering", "Sec 17(5)(b)(i)",
         _w("food", "foods", "meals?", "canteen", "cater(?:er|ers|ing)", "restaurants?", "refreshments?",
            "snacks?", "beverages?", "tea", "coffee", "samosas?", "namkeen", "sweets", "mithai", "lunch", "dinner", "breakfast", "tiffin", "pantry", "banquet",
            "staff welfare", "business meals?", "f ?& ?b"),
         hsn=("99633",), goods=True,
         unless=_w("factories act", "statutory canteen", "u/s 46", "obligat\\w* (?:under|by) (?:law|the)",
                   "canteen (?:building|block|construction|shed|civil)"),
         exceptions="Allowed if used to make an outward supply of the same kind (e.g. a caterer) or as part "
                    "of a taxable composite/mixed supply, or if the employer must provide it under a law."),
    Rule("beauty_health", "Beauty treatment / health services / cosmetic surgery", "Sec 17(5)(b)(i)",
         _w("beauty", "salon", "parlou?r", "spa", "cosmetic", "plastic surgery",
            "hospital(?!\\s*(?:project|building|construction|site|block|wing|campus|works?))",
            "clinic", "health ?check(?:-?up)?", "diagnostics?",
            "medical (?:expenses|treatment|reimbursement|services|bills?|check(?:-?up)?)", "doctor", "opd",
            "polyclinic", "consultation fees? - doctor", "dental", "physiotherapy"),
         hsn=("9993", "999721", "999722"), goods=True,          # 99932-99935 (social care) excluded below
         exceptions="Allowed if used for an outward supply of the same kind or as part of a taxable composite/"
                    "mixed supply, or if the employer must provide it under a law (Circular 172/04/2022)."),
    Rule("insurance", "Life / health insurance", "Sec 17(5)(b)(i)",
         _w("life insurance", "health insurance", "medi-?claim", "group health", "group medical", "gmc",
            "term (?:life )?insurance", "keyman (?:insurance|policy)", "gmc (?:policy|premium|insurance)"),
         unless=_w("statutory", "obligat\\w* (?:under|by) (?:law|the)"),
         exceptions="Allowed if the employer must provide it under a law, or for an outward supply of the "
                    "same kind. Individual life/health policies are GST-exempt since 22 Sep 2025, so this "
                    "mainly affects group policies."),
    Rule("motor_vehicle", "Motor vehicle (up to 13 seats) - purchase, hire, repair or insurance",
         "Sec 17(5)(a), (ab), (b)(i)",
         _w("cars?", "motor ?cars?", "scooters?", "motorcycles?", "two[- ]wheelers?", "cabs?", "taxi",
            "vehicle (?:repairs?|maintenance|servicing|insurance|hire|rent(?:al)?|lease|running|expenses|upkeep)",
            "car (?:repairs?|maintenance|servicing|insurance|hire|rent(?:al)?|lease|expenses)",
            "vehicle exp\\.?", "innova", "fortuner", "creta", "scorpio", "xuv ?\\d*", "ertiga", "dzire",
            "baleno", "honda city", "verna", "brezza", "nexon", "activa", "splendor", "bullet"),
         hsn=("8703", "8711", "9966"), goods=True,      # 996602/996603 (vessels/aircraft) handled below
         maybe=_w("conveyance", "vehicles?"),          # bare 'vehicle' only counts in a ledger name
         unless=_w("goods vehicles?", "trucks?", "lorry", "lorries", "tempo", "freight", "transport of goods",
                   "carriage", "cargo", "cartons?", "(?:spare )?parts", "spares", "components?",
                   "accessories", "driving school", "dual control", "tourist taxi", "taxi business",
                   "passenger transport", "(?:13|1[4-9]|[2-9]\\d)[- ]seat(?:er|s)?", "bus", "buses", "jcb",
                   "forklift", "tractor", "coach", "staff bus"),
         exceptions="Not blocked at all: goods vehicles, and vehicles with more than 13 seats incl. driver. "
                    "Allowed when used for further supply of vehicles, passenger transport or driving training. "
                    "Repair/insurance also allowed to vehicle manufacturers and to general insurers covering them. "
                    "Hire also allowed for an outward supply of the same kind, or where a law obliges the employer."),
    Rule("club", "Club / health and fitness centre membership", "Sec 17(5)(b)(ii)",
         _w("club", "clubs", "club membership", "gym", "gymnasium", "fitness"),
         hsn=("999723",),
         exceptions="Blocked unless the employer must provide it under a law (Circular 172/04/2022). Check it is "
                    "not a professional body's fee (ICAI, chamber of commerce), which is not a club."),
    Rule("travel_vacation", "Travel benefit to employees on vacation", "Sec 17(5)(b)(iii)",
         _w("ltc", "leave travel", "home travel", "holiday package", "tour package", "vacation", "picnic",
            "staff (?:tour|trip|outing)", "employee (?:tour|trip|outing)"),
         exceptions="Business travel is not blocked; only leave / home-travel benefits are. Allowed where the "
                    "employer must provide it under a law (Circular 172/04/2022)."),
    Rule("construction", "Construction of immovable property / works contract", "Sec 17(5)(c), (d)",
         _w("construction", "civil works?", "civil", "building (?:work|construction)", "renovation",
            "interior (?:works?|decoration|fit-?outs?)", "fit-?outs?", "false ceiling", "flooring work",
            "buildings?", "shed", "pre-?engineered", "peb", "boundary wall", "compound wall", "pipeline work",
            "precast drains?", "pre cast drains?", "rcc", "concreting"),
         hsn=("9954",),
         maybe=_w("works contract", "works contract services"),   # also used for plant & machinery installation
         unless=_w("repairs?", "repair (?:&|and) maint\\.?", "maintenance", "revenue", "p ?& ?l", "painting",
                   "machine(?:ry)? foundation", "foundation for", "plant (?:&|and) machinery", "rent", "rental",
                   "gantry", "gantry girders?", "crane (?:girders?|rails?|supports?)", "structural supports? for",
                   "equipment (?:foundation|supports?)"),
         exceptions="New construction on own account is blocked; renovation, additions and repairs only to the "
                    "extent capitalised. Plant and machinery is outside the block, but it excludes land, buildings, "
                    "other civil structures, telecom towers and pipelines laid outside the factory. Repairs charged "
                    "to expenses, and works contractors supplying works contracts onward, can claim. Finance Act "
                    "2025 (retrospective from 1 Jul 2017) reads 'plant or machinery' as 'plant and machinery', "
                    "overriding Safari Retreats; its validity is being challenged in High Courts."),
    Rule("gifts", "Goods given as gifts / free samples", "Sec 17(5)(h)",
         _w("gifts?", "diwali gifts?", "free samples?", "giveaways?", "hampers?", "mementos?"), goods=True,
         maybe=_w("business promotion", "festival(?: exp\\.?| expenses)?", "diwali"),
         exceptions="Goods only. Not blocked where the gift is a supply under Schedule I (e.g. to a related "
                    "person in the course of business). Buy-one-get-one and discount offers are not gifts "
                    "(Circular 92/11/2019)."),
    Rule("lost_destroyed", "Goods lost, stolen, destroyed or written off", "Sec 17(5)(h)",
         _w("written off", "write[- ]off", "stock loss", "loss of stock", "theft", "stolen", "destroyed",
            "obsolete stock", "shortage", "expired stock", "damaged stock", "loss by fire"),
         exceptions="ITC on goods lost, stolen, destroyed or written off must be reversed. Normal process loss "
                    "in manufacturing is not covered."),
    Rule("vessel_aircraft", "Vessels and aircraft", "Sec 17(5)(aa)",
         _w("aircraft", "helicopter", "yacht", "boat", "air charter", "chartered (?:plane|flight)", "vessel"),
         hsn=("8802", "8901", "8903", "996602", "996603"), goods=True,
         unless=_w("cargo", "freight", "air ticket", "airfare", "flight tickets?", "shipping charges"),
         exceptions="Allowed when used for further supply, transport of passengers or goods, flying/navigation "
                    "training. Repair/insurance also allowed to manufacturers and general insurers."),
    Rule("csr", "Corporate social responsibility (CSR)", "Sec 17(5)(fa)",
         _w("csr", "corporate social responsibility", "sec(?:tion|\\.)? ?135"),
         exceptions="Goods or services used for CSR obligations are blocked."),
    Rule("personal", "Personal consumption", "Sec 17(5)(g)",
         _w("personal", "household", "residence", "family",
            "(?:partner|director|owner|proprietor|md|chairman)'?s? (?:son|daughter|wife|husband|family|house|home|"
            "residence|personal|use)"),
         unless=_w("personal protective", "ppe", "personal care products?"),
         exceptions="Blocked if used for the owner's or a director's personal use."),
]
_HOTEL = _w("hotels?", "resorts?", "inns?", "guest ?house", "residency")
_LODGING = _w("lodging", "accommodation", "accomodation", "acommodation", "rooms?", "room rent", "room tariff", "room charges", "stay", "rent",
              "hall (?:rent|hire|charges)", "conference (?:hall|room)", "venue (?:rent|hire)")
_FOOD = RULES[0].words
_NO_FOOD = _w("room only", "no f ?& ?b", "no food", "without (?:food|meals)", "excluding (?:food|meals|f ?& ?b)",
              "ep plan")                                     # EP = European plan, room only
_BREAKFAST = _w("breakfast", "complimentary breakfast", "cp plan", "with breakfast")
_MIXED = _w("boarding", "cp plan", "map plan", "ap plan")    # boarding / meal plans include food
# Goods bought for further supply are an exception to most blocks (car dealer, caterer, gift shop).
_RESALE = _w("resale", "re-sale", "for sale", "stock[- ]in[- ]trade", "trading stock", "for assembly",
             "raw materials?", "inventory")
_PURCHASE_LEDGER = re.compile(r"^\s*purchases?\b", re.I)    # Tally trading ledgers: 'Purchase - Vehicles'


@dataclass
class Flag:
    rid: str
    label: str
    section: str
    confidence: str            # 'Likely' (ledger/description/HSN) or 'Possible' (supplier name only) or 'Review'
    evidence: str
    advice: str
    exceptions: str = ""

    def text(self) -> str:
        return (f"Possible blocked credit - {self.label} ({self.section}); {self.confidence.lower()}: "
                f"{self.evidence}. {self.advice}")


def _sources(docs):
    """(field label, text, strong?) for every place a clue might be."""
    out = []
    for d in docs:
        if d.hsn:
            out.append(("HSN/SAC", d.hsn, True))
        if d.ledger:
            out.append(("ledger", d.ledger, True))
        if d.description:
            out.append(("description", d.description, True))
    for d in docs:
        if d.supplier_name:
            out.append(("supplier name", d.supplier_name, False))
    return out


def classify(docs) -> list[Flag]:
    """Blocked-credit flags for one decision's documents (books first, then 2B)."""
    flags: list[Flag] = []
    seen = set()
    srcs = _sources(docs)
    codes = [re.sub(r"\D", "", t) for f, t, _ in srcs if f == "HSN/SAC"]
    texts = [(f, t, strong) for f, t, strong in srcs if f != "HSN/SAC"]
    strong_text = " ".join(t for _, t, strong in texts if strong)
    for_supply = bool(_RESALE.search(strong_text)) or any(f == "ledger" and _PURCHASE_LEDGER.search(t)
                                                          for f, t, _ in texts)
    if for_supply and _RESALE.search(strong_text):
        return flags        # explicitly bought to sell / build into a product: the Sec 17(5) blocks don't apply

    # Hotels: a room for business is allowed, food on the same bill is not.
    hotel_hit = next(((f, t) for f, t, _ in texts if _HOTEL.search(t)), None)
    statutory_food = bool(RULES[0].unless.search(strong_text))
    if (hotel_hit or any(c.startswith("9963") for c in codes)) and not statutory_food \
            and not (for_supply and not hotel_hit):
        food_text = _NO_FOOD.sub(" ", strong_text)
        no_food = bool(_NO_FOOD.search(strong_text))
        food_hit = _FOOD.search(food_text) or any(c.startswith("99633") for c in codes)
        lodging = (_LODGING.search(strong_text) or any(c.startswith(("99631", "99632", "9972")) for c in codes)) \
            and not _MIXED.search(strong_text)
        lodging_only = (lodging or no_food) and not food_hit
        # breakfast in a room tariff at one price is a composite supply of accommodation: check, don't presume
        breakfast_only = lodging and food_hit and not any(c.startswith("99633") for c in codes) and \
            _BREAKFAST.search(food_text) and not _FOOD.search(_BREAKFAST.sub(" ", food_text))
        if breakfast_only:
            f, t = hotel_hit or ("HSN/SAC", "9963")
            flags.append(Flag("hotel_mixed", "Hotel bill - room with breakfast", "Sec 17(5)(b)(i)", "Review",
                              f"{f} '{t}'",
                              "Breakfast included in the room tariff at one price is a composite supply of "
                              "accommodation and is generally allowed; food charged separately is blocked. "
                              "Check the bill.", RULES[0].exceptions))
            seen.add("food")
        elif not lodging_only:
            if food_hit:
                ev = next((f"{f} '{t}'" for f, t, st in texts if st and _FOOD.search(_NO_FOOD.sub(" ", t))), None) or \
                    "SAC " + next((c for c in codes if c.startswith("99633")), "9963")
                flags.append(Flag("food", RULES[0].label, RULES[0].section, "Likely", ev,
                                  "Food billed separately by a hotel (restaurant, room service, minibar) is blocked; reverse that "
                                  "part in GSTR-3B Table 4(B)(1).",
                                  RULES[0].exceptions))
            else:
                f, t = hotel_hit or ("HSN/SAC", "9963")
                flags.append(Flag("hotel_mixed", "Hotel bill - room vs food", "Sec 17(5)(b)(i)", "Review",
                                  f"{f} '{t}'",
                                  "Room stay for business is allowed; food and beverages on the bill are "
                                  "blocked. Check the bill split before claiming.",
                                  RULES[0].exceptions))
            seen.add("food")
        else:
            seen.add("food")     # room only: the 'F&B' / 'no food' wording must not trip the food rule

    for rule in RULES:
        if rule.rid in seen or (rule.goods and for_supply):
            continue
        hit = None
        # e.g. SAC 9966 covers hiring cars AND trucks: a ledger saying 'goods vehicle' rules the block out
        ruled_out = bool(rule.unless) and any(rule.unless.search(t) for _, t, strong in texts if strong)
        if ruled_out:
            continue
        for c in codes:
            if any(c.startswith(p) for p in rule.hsn) and not (rule.rid == "food" and c.startswith("99631")) \
                    and not (rule.rid == "motor_vehicle" and c.startswith(("996602", "996603"))) \
                    and not (rule.rid == "beauty_health" and c.startswith(("99932", "99933", "99934", "99935"))):
                hit = ("Likely", f"HSN/SAC {c}")
                break
        if not hit:
            for f, t, strong in texts:
                m = rule.words.search(t)
                if m and not (rule.unless and rule.unless.search(t)):
                    hit = ("Likely" if strong else "Possible", f"{f} '{t}'")
                    break
        if not hit and rule.maybe:
            for f, t, strong in texts:
                m = rule.maybe.search(t) if strong else None
                if m and rule.rid == "motor_vehicle" and m.group(0).lower().startswith("vehicle") and f != "ledger":
                    continue        # 'commercial vehicle plant', 'cost per vehicle': only a ledger name counts
                if m:
                    hit = ("Possible", f"{f} '{t}'")
                    break
        if hit:
            seen.add(rule.rid)
            flags.append(Flag(rule.rid, rule.label, rule.section, hit[0], hit[1],
                              "If blocked: leave it in GSTR-3B Table 4(A)(5) as auto-filled and reverse it in Table 4(B)(1); that reversal is permanent (Circular 170/02/2022-GST).",
                              rule.exceptions))
    return flags


# A client's own line of business removes blocks that exist only for end use
# (Sec 17(5) exceptions for 'further supply of the same category'). Tags are set per client.
LINES_OF_BUSINESS = {
    "vehicle_maker": "Makes motor vehicles: repair, servicing and insurance of vehicles, and vehicles bought "
                     "for supply, are allowed (Sec 17(5)(a)/(ab)). Hire of cabs for staff is still blocked.",
    "vehicle_dealer": "Deals in motor vehicles: vehicles bought for resale, and their repair/insurance, are allowed.",
    "caterer": "Restaurant / caterer / food business: food and beverages bought for its own supply are allowed.",
    "hotel": "Hotel: food, rooms and related inputs for its own supply are allowed.",
    "works_contractor": "Works contractor: construction inputs used to supply works contracts onward are allowed.",
    "insurer": "General / health insurer: insurance-related inputs are allowed.",
    "travel_operator": "Tour operator / cab operator: vehicle hire and travel packages for onward supply are allowed.",
    "gym_club": "Runs a club or fitness centre: memberships and related inputs for its own supply are allowed.",
}
_OWN_USE = re.compile(r"personal|own use|md'?s|director|chairman|partner'?s|proprietor|staff|employee|"
                      r"for (?:our|the company'?s) use", re.I)
_STAFF_FOOD = re.compile(r"staff|employee|cafeteria|canteen|welfare|team (?:lunch|dinner)|party", re.I)
_OWN_BUILDING = re.compile(r"own (?:office|building|premises|factory|godown|warehouse)|our (?:office|building)|"
                           r"head office|capitali[sz]ed|for own use", re.I)
_GUESTS = re.compile(r"guests?|airport (?:transfer|pick)|pick ?-?up|drop", re.I)
_LOB_SUPPRESS = {      # (flag, all the record's text) -> True when the client's own business makes it allowed
    "vehicle_maker": lambda fl, t: fl.rid == "motor_vehicle" and not re.search(
        r"hire|rent|lease|cab|taxi|fms", t, re.I) and not _OWN_USE.search(t),
    "vehicle_dealer": lambda fl, t: fl.rid == "motor_vehicle" and not re.search(
        r"hire|rent|lease|cab|taxi|fms", t, re.I) and not _OWN_USE.search(t),
    "caterer": lambda fl, t: fl.rid == "food" and not _STAFF_FOOD.search(t),
    "hotel": lambda fl, t: (fl.rid in ("food", "hotel_mixed") and not _STAFF_FOOD.search(t))
    or (fl.rid == "motor_vehicle" and bool(_GUESTS.search(t))),
    "works_contractor": lambda fl, t: fl.rid == "construction" and not _OWN_BUILDING.search(t),
    "insurer": lambda fl, t: fl.rid in ("insurance",) or (fl.rid == "motor_vehicle" and "insur" in t.lower()),
    "travel_operator": lambda fl, t: fl.rid in ("travel_vacation", "motor_vehicle"),
    "gym_club": lambda fl, t: fl.rid == "club",
}


def _record_text(docs) -> str:
    return " | ".join(x for d in docs for x in (d.ledger, d.description, d.hsn) if x)


def _lob_tags(lob) -> set:
    if not lob:
        return set()
    if isinstance(lob, str):
        lob = re.split(r"[,;\s]+", lob)
    return {t.strip().lower() for t in lob if t and t.strip().lower() in LINES_OF_BUSINESS}


def apply(findings: list[Finding], line_of_business=None) -> None:
    """Attach blocked-credit flags to every decision that carries ITC.

    `line_of_business`: tags from LINES_OF_BUSINESS for this client (e.g. 'caterer'), which switch off
    blocks that do not apply to what the client itself supplies. The firm's own ITC-eligibility mark
    (vendor master / register column) is used too: 'No' raises a flag, 'Yes' is shown next to ours."""
    tags = _lob_tags(line_of_business)
    for f in findings:
        if f.status.value == "No GST on this entry":
            continue                      # no ITC on it, so nothing can be blocked
        docs = [d for d in f.books + f.portal if d.doc_type != DocType.CREDIT_NOTE]
        if not docs:
            # a credit note against a blocked bill: not a decision to review, but it lowers the 4(B)(1)
            # reversal (gstr3b reads this)
            cn = [d for d in f.books + f.portal]
            if cn:
                txt = _record_text(cn)
                f.blocked_cn = [fl for fl in classify(cn) if not any(_LOB_SUPPRESS[t](fl, txt) for t in tags)]
            continue
        flags = classify(f.books + [d for d in f.portal if d not in f.books])
        txt = _record_text(docs)
        for t in tags:
            kept = [fl for fl in flags if not _LOB_SUPPRESS[t](fl, txt)]
            if len(kept) < len(flags):
                f.flags.append(f"Not flagged as blocked credit: {LINES_OF_BUSINESS[t]}")
            flags = kept
        marks = [d.eligible for d in docs if d.eligible is not None]
        firm_no = bool(marks) and all(m is False for m in marks)
        firm_yes = bool(marks) and all(m is True for m in marks)
        if firm_no and not flags:
            flags = [Flag("firm_ineligible", "Marked ineligible in your own records", "Sec 16 / 17(5) (as marked)",
                          "Likely", "the ITC-eligibility column says 'No'",
                          "Your vendor master / register marks this ITC as not eligible. If it is blocked, reverse "
                          "it in GSTR-3B Table 4(B)(1); if this bill is different, correct the mark.")]
        elif firm_yes:
            for fl in flags:
                fl.evidence += "; your own records mark it eligible - confirm which is right"
        if flags:
            f.blocked = flags
            for fl in flags:
                f.flags.append(fl.text())
