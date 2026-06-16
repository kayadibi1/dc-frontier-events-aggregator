"""Static configuration: sources, watchlists, topic + location matchers.

Everything the pipeline keys on (which calendars to pull, what counts as
on-topic, who the "big names" are, where "DC metro" is) lives here so it can
be tuned without touching pipeline code. The big-name watchlist living in
config is mandated by GOAL.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    slug: str          # short id, e.g. "DC2" / "cset"
    name: str          # human label
    kind: str          # adapter kind: "luma" | "cset"
    layer: int         # 1=builder/community, 2=policy, 3=university
    dc_curated: bool   # True if the source is itself DC-scoped (trusted location)
    cal_id: str = ""   # luma calendar id ("cal-…") or discover place id ("discplace-…")
    url: str = ""      # listing page for HTML scrapers


# Layer 1 — Luma calendars + the DC city discover feed (api.lu.ma JSON).
LUMA_SOURCES = [
    Source("DC2", "DC Data & AI Events", "luma", 1, True, cal_id="cal-eCuIBRbS1atJOa6"),
    Source("DCtechevents", "Washington DC Tech Events", "luma", 1, True, cal_id="cal-0TDb3WUDzBp2DYy"),
    Source("dctech", "DC Tech & Venture Coalition", "luma", 1, True, cal_id="cal-Q37RKijUFFdzt97"),
    # Single-city DC chapters (added iter F7); geo-authority still drops stray non-DC events.
    Source("ai-tinkerers-dc", "AI Tinkerers DC", "luma", 1, True, cal_id="cal-QhC1Y2193RQ7sZ6"),
    Source("dctechmeetup", "DC Tech Meetup", "luma", 1, True, cal_id="cal-GzmqNpNKPBSmYdl"),
    # AI Collective's calendar is global (SF/NYC/Chicago/... events), not DC-only:
    # ~11 of ~455 events are in DC. NOT dc_curated, so it is held to the strict
    # DC geo/text filter and only its genuinely-DC events are kept.
    Source("aic-washington", "AI Collective DC", "luma", 1, False, cal_id="cal-E74MDlDKBaeAwXK"),
    # REMOVED 2026-06-09: "ai" (Global AI, cal-nyk2WcWIv2CFmq8) — Luma turned it
    # into a discover calendar (disccal-…), which has no ICS export (404s).
    # City-wide net: every public DC-area Luma event, whatever the calendar.
    # NOT dc_curated -- the strict topic/geo filter keeps only on-topic events.
    Source("luma-dc", "Luma DC (city-wide)", "luma-discover", 1, False,
           cal_id="discplace-AANPgOymN6bqFn8"),
]

# Layer 1 — Meetup groups (per-group public iCal export). DC-specific data/AI
# communities; geo-authority still drops any stray non-DC event. The .ics carries
# the venue, so on-topic DC meetups pin on the map.
MEETUP_SOURCES = [
    Source("meetup-dsdc", "Data Science DC", "ics", 1, True,
           url="https://www.meetup.com/data-science-dc/events/ical/"),
    Source("meetup-dataviz", "Data Visualization DC", "ics", 1, True,
           url="https://www.meetup.com/data-visualization-dc/events/ical/"),
]

# Layer 2 — policy / big-name (the high-signal tier). HTML scrape behind a WAF,
# so the adapter uses curl_cffi (browser TLS impersonation). CSET is a DC
# institution (125/500 ... NW, Washington DC) -> dc_curated.
CSET_SOURCES = [
    Source("cset", "CSET (Georgetown)", "cset", 2, True, url="https://cset.georgetown.edu/events/"),
    # CSIS HQ is in DC (1616 Rhode Island Ave NW); httpx-accessible.
    Source("csis", "CSIS", "csis", 2, True, url="https://www.csis.org/events"),
    # Brookings HQ is in DC (1775 Massachusetts Ave NW); httpx-accessible.
    Source("brookings", "Brookings", "brookings", 2, True, url="https://www.brookings.edu/events/"),
    # CNAS HQ is in DC (1701 Pennsylvania Ave NW); httpx-accessible. Strong AI/chip
    # policy slate (US-China AI competition, Project Maven, Pentagon & Silicon Valley).
    Source("cnas", "CNAS", "cnas", 2, True, url="https://www.cnas.org/events"),
    # Atlantic Council HQ is in DC (1400 L St NW); WAF -> curl_cffi adapter. AI-era
    # strategy + AI/bio events ("How the US and allies can win the AI era").
    Source("atlanticcouncil", "Atlantic Council", "atlanticcouncil", 2, True,
           url="https://www.atlanticcouncil.org/events/"),
    # NIST (Gaithersburg MD = DC metro, but ALSO a Boulder CO campus) -> NOT
    # dc_curated; kept only via a real DC venue/text so a Boulder event can't slip
    # in. Detail pages carry schema.org Event JSON-LD (enriched via structured.py).
    Source("nist", "NIST", "nist", 2, False, url="https://www.nist.gov/news-events/events"),
    # ITIF (Information Technology & Innovation Foundation) HQ is in DC (700 K St
    # NW); WAF -> curl_cffi. A top AI/semiconductor/compute tech-policy shop. Its
    # events page is a Next.js app -- the full slate is embedded as JSON in
    # __NEXT_DATA__ (no card-scraping). Detail pages carry og:description.
    Source("itif", "ITIF", "itif", 2, True, url="https://itif.org/events/"),
    # CDT (Center for Democracy & Technology) HQ is in DC (1401 K St NW);
    # httpx-accessible. AI governance / kids-online-safety / privacy policy. Clean
    # h-event microformat listing (tz-aware dt-start). The topic gate drops its
    # off-topic / non-DC (e.g. EU/Brussels) items.
    Source("cdt", "CDT", "cdt", 2, True, url="https://cdt.org/events/"),
    # National Academies (NASEM): high-signal AI/computing/semiconductor studies &
    # workshops, often at its DC venues but ALSO Irvine CA -> NOT dc_curated (kept
    # only via a real DC venue/text). curl_cffi. Listing cards: a[href*='/event/'].
    Source("nasem", "National Academies", "nasem", 2, False,
           url="https://www.nationalacademies.org/events"),
    # Additional DC policy / NGO sources (2026-06 source expansion). These are
    # detail-page adapters: listings discover candidates, detail pages provide
    # date/time/location/attendance-mode. Broad global/multi-office orgs stay
    # NOT dc_curated so only real DC-metro or explicitly DC/virtual items survive.
    Source("hudson", "Hudson Institute", "hudson", 2, True,
           url="https://www.hudson.org/events"),
    Source("aei", "American Enterprise Institute", "aei", 2, True,
           url="https://www.aei.org/events/"),
    Source("bpc", "Bipartisan Policy Center", "bpc", 2, True,
           url="https://bipartisanpolicy.org/events/"),
    # New America is DC-headquartered but its event program is national (e.g.
    # non-DC in-person venues), so do not trust curation alone for location.
    Source("newamerica", "New America", "newamerica", 2, False,
           url="https://www.newamerica.org/events/"),
    Source("heritage", "Heritage Foundation", "heritage", 2, True,
           url="https://www.heritage.org/events"),
    Source("carnegie", "Carnegie Endowment", "carnegie", 2, False,
           url="https://carnegieendowment.org/events"),
    Source("rand", "RAND", "rand", 2, False,
           url="https://www.rand.org/events.html"),
    Source("wilson", "Wilson Center", "wilson", 2, True,
           url="https://www.wilsoncenter.org/events"),
    # SCSP is Arlington-based but runs AI+ events in other cities too; require a
    # real DC-metro/virtual signal instead of pinning all events to HQ.
    Source("scsp", "Special Competitive Studies Project", "scsp", 2, False,
           url="https://www.scsp.ai/events/"),
    Source("stimson", "Stimson Center", "stimson", 2, True,
           url="https://www.stimson.org/all-events/"),
    Source("fas", "Federation of American Scientists", "fas", 2, True,
           url="https://fas.org/events/"),
    Source("mercatus", "Mercatus Center", "mercatus", 2, True,
           url="https://www.mercatus.org/events"),
    # U.S. Congress committee hearings (congress.gov API) -- the highest-signal DC
    # policy source, year-round. All on Capitol Hill -> dc_curated. Needs
    # CONGRESS_API_KEY in the env; skipped (quarantined) without it.
    Source("congress", "U.S. Congress", "congress", 2, True,
           url="https://api.congress.gov/v3/committee-meeting"),
    # AI Security Forum -- recurring DC edition. Notion/Super.so site; the DC
    # editions use a stable `dc-ai-security-forum-NN` slug, so future editions are
    # auto-discovered from the listing and dated from each event page. dc_curated
    # (the slug + page venue are DC by construction). httpx + neutral UA.
    Source("aisf", "AI Security Forum (DC)", "aisf", 2, True,
           url="https://aisecurity.forum/events"),
    # Council on Strategic Risks: AI/national-security events. WordPress events
    # RSS for discovery, then the bolded event date on each post. Runs global
    # (London/virtual) events too -> NOT dc_curated; the DC filter keeps only
    # real DC-metro items. nginx, httpx-accessible.
    Source("cosr", "Council on Strategic Risks", "cosr", 2, False,
           url="https://councilonstrategicrisks.org/category/events/feed/"),
    # Curated marquee company / semiconductor events (the watchlist adapter reads
    # WATCHLIST_EVENTS, not a URL) -- for high-prestige orgs that publish no feed.
    # All DC-metro, hand-verified; self-pruning. dc_curated.
    Source("watchlist", "Curated marquee (DC)", "watchlist", 2, True),
]

# Layer 3 — universities. Localist exposes a campus-wide iCal feed; the topic
# filter extracts the AI/chip events from the full calendar. GWU is in DC
# (Foggy Bottom) -> dc_curated. Uses the generic iCal adapter.
UNIVERSITY_SOURCES = [
    Source("gwu", "George Washington University", "ics", 3, True,
           url="https://calendar.gwu.edu/calendar.ics"),
    # Howard University (DC, Georgia Ave NW) -> dc_curated; Localist iCal feed.
    Source("howard", "Howard University", "ics", 3, True,
           url="https://events.howard.edu/calendar.ics"),
    # UMD Computer Science (College Park, in the DC bbox) -> dc_curated. Strong
    # AI/ML/robotics/NLP dept; Drupal events listing with an authoritative dc:date
    # start. Seasonal: quiet summer, full fall. Bespoke `umdcs` adapter.
    Source("umdcs", "University of Maryland (CS)", "umdcs", 3, True,
           url="https://www.cs.umd.edu/events"),
    # Georgetown Law (its Tech Institute runs an AI-governance series). WordPress
    # The Events Calendar REST feed -- but it's the WHOLE law-school calendar
    # (alumni/moot-court, some Bay Area events), so NOT dc_curated + strict TITLE
    # topic gate keeps only its DC AI/chip events. httpx-accessible (no WAF).
    Source("gtlaw", "Georgetown Law", "gtlaw", 3, False,
           url="https://www.law.georgetown.edu/wp-json/tribe/events/v1/events"),
]

SOURCES = LUMA_SOURCES + MEETUP_SOURCES + CSET_SOURCES + UNIVERSITY_SOURCES

# Per-source hints for the headless jsrender adapter (extract.py). Optional CSS
# selectors / strategy per source slug; a missing entry uses the generic layered
# extractor (JSON-LD -> __NEXT_DATA__ -> heuristic cards). Keys: wait_for, card,
# title, date, link, location.
JSRENDER_HINTS: dict[str, dict] = {}

# Curated marquee events for orgs that publish no event feed at all (watchlist
# adapter). Each entry: {"name","date","venue"(full DC-metro address),"url","topics"}.
# The adapter self-prunes -- past-dated or dead-link entries are dropped each run.
# Add a NEW edition's date when announced (these recur). All hand-verified live.
WATCHLIST_EVENTS: list[dict] = [
    {"name": "AWS Summit Washington, D.C. 2026", "date": "2026-06-30",
     "venue": "Walter E. Washington Convention Center, 801 Allen Y. Lew Place NW, Washington, DC 20001",
     "url": "https://aws.amazon.com/events/summits/washington-dc/", "topics": ["ai", "compute"]},
    {"name": "Semiconductor Fab Design, Engineering & Construction Summit USA 2026",
     "date": "2026-06-24", "venue": "Falls Church Marriott Fairview Park, Falls Church, VA",
     "url": "https://future-bridge.us/semiconductor-fab-design-construction-summit-2026/",
     "topics": ["semiconductor"]},
    {"name": "USA Artificial Intelligence Summit 2026", "date": "2026-06-17",
     "venue": "Washington, DC", "url": "https://us-aisummit.com/", "topics": ["ai"]},
    {"name": "Government & AI Summit 2026", "date": "2026-09-15",
     "venue": "JW Marriott, 1331 Pennsylvania Ave NW, Washington, DC",
     "url": "https://events.govexec.com/government-ai-summit-2026/home/", "topics": ["ai"]},
    {"name": "Future of Our Realities 2026: Work and Truth", "date": "2026-06-20",
     "venue": "555 Pennsylvania Avenue NW, Washington, DC 20001",
     "url": "https://futurerealities.org/FOR2026/", "topics": ["ai"]},
    {"name": "Horizon AI Innovation and Security Policy Workshop", "date": "2026-08-21",
     "venue": "Washington, DC",
     "url": "https://horizonpublicservice.org/apply-for-the-ai-innovation-security-policy-workshop/",
     "topics": ["ai", "policy"]},
]


# Topic relevance. Canonical topic -> regex (case-insensitive, word-boundaried
# for short/ambiguous tokens so "ai" does not match "email" / "html").
TOPIC_PATTERNS = {
    "ai": r"\bai\b|\bartificial intelligence\b|\ba\.i\.\b",
    "ml": r"\bml\b|\bmachine learning\b",
    "llm": (r"\bllms?\b|large language model|\bgpt\b|generative ai|gen-?ai|"
            r"chatbots?|foundation models?|\bai agents?\b|agentic ai"),
    "deep-learning": r"deep learning|neural network|\bnlp\b|computer vision|transformer|multimodal",
    "data-science": r"data science|data scientist|\banalytics\b|data engineer|big data|\bdataset\b",
    "semiconductor": r"semiconductor|\bchips?\b|fab(rication)?\b|foundry|\btsmc\b|wafer|\basml\b",
    # NB: bare "accelerat" was removed — it matched "accelerated <degree>" in
    # university boilerplate (Nursing Tour, MBA programs). Bare "accelerator" was
    # then narrowed too: it matched program/org names ("startup accelerator",
    # "Vaccine Manufacturing Accelerator"). Keep only hardware/AI accelerators +
    # "accelerated computing".
    "compute": (r"\bgpus?\b|datacenter|data center|\bcompute\b|\bcuda\b|"
                r"(?:ai|gpu|hardware|neural|inference|training|silicon|chip|tpu)[ -]accelerators?|"
                r"accelerated comput|\bhpc\b"),
    "policy": r"export control|chips act|ai policy|ai safety|ai governance|frontier model|ai regulation",
    "robotics": r"\brobots?\b|robotic|autonomous vehicle|self-driving",
}

# Big-name watchlist — orgs and people. A match sets is_big_name.
BIG_NAME_PATTERNS = {
    # --- frontier AI labs / big tech ---
    # NB: deliberately NOT bare "google"/"meta"/"apple" — they match "Google Form",
    # "metadata", "Big Apple" etc. Use product/specific tokens instead.
    "Anthropic": r"\banthropic\b|\bclaude\b",
    "OpenAI": r"\bopenai\b|\bchatgpt\b",
    "Google DeepMind": r"\bdeepmind\b|google deepmind|google ai|\bgemini\b",
    "Microsoft": r"\bmicrosoft\b(?!\s*(?:365|office|teams|word|excel|outlook|powerpoint|onenote|sharepoint|access|publisher))",
    "Meta AI": r"\bmeta ai\b|\bllama\b",
    "Amazon": r"\bamazon\b|\baws\b",
    "Mistral": r"\bmistral\b",
    "Cohere": r"\bcohere\b",
    "Hugging Face": r"\bhugging face\b",
    "Scale AI": r"\bscale ai\b",
    "Databricks": r"\bdatabricks\b",
    "Palantir": r"\bpalantir\b",
    # More frontier labs. Patterns are deliberately specific to dodge landmines:
    # "inflection ai" not bare "inflection" (inflection point), "stability ai"
    # not "stability", "perplexity ai" not bare "perplexity" (the NLP metric).
    # "grok" only: bare "xai" collides with eXplainable AI (XAI), common in ML/
    # academic titles, so it must NOT flag the event as the Elon xAI company.
    "xAI": r"\bgrok\b",
    "Inflection AI": r"\binflection ai\b",
    "Stability AI": r"\bstability ai\b",
    "Together AI": r"\btogether ai\b",
    "Perplexity": r"\bperplexity ai\b",
    # --- semiconductor / compute ---
    "Nvidia": r"\bnvidia\b",
    "AMD": r"\bamd\b",
    # AI-accelerator chip companies (the user's chip/compute angle). Distinctive
    # names; "groq" is the company's deliberate respelling, distinct from "grok".
    "Groq": r"\bgroq\b",
    "Cerebras": r"\bcerebras\b",
    "SambaNova": r"\bsambanova\b",
    "Micron": r"\bmicron technology\b",  # not bare "micron" (the unit)
    # "Intel" (company) but not DC's ubiquitous "intel community"/"intelligence".
    "Intel": r"\bintel\b(?! (?:community|officer|officers|agency|agencies|analyst|analysts|"
             r"sharing|assessment|assessments|brief|briefing|gathering))",
    "TSMC": r"\btsmc\b",
    "ASML": r"\basml\b",
    "Qualcomm": r"\bqualcomm\b",
    "Broadcom": r"\bbroadcom\b",
    "IBM": r"\bibm\b",
    # --- DC policy ecosystem (the user's AI/chip policy angle is first-class
    # prestige). Distinctive acronyms/phrases only -- "rand corporation" not bare
    # "rand" (Rand Paul / brand / errand), "ai safety institute" for CAISI. ---
    "CSET": r"\bcset\b",
    "CSIS": r"\bcsis\b",
    "CNAS": r"\bcnas\b",
    "NIST": r"\bnist\b",
    "CAISI": r"\bcaisi\b|\bai safety institute\b",
    "RAND": r"\brand corporation\b",
    "Brookings": r"\bbrookings\b",
    "Atlantic Council": r"\batlantic council\b",
    # --- people: company leaders + key AI researchers + DC AI/chip policy figures ---
    "Dario Amodei": r"\bdario amodei\b|\bamodei\b",
    "Sam Altman": r"\bsam altman\b|\baltman\b",
    "Jensen Huang": r"\bjensen huang\b|\bjensen\b",
    "Brad Smith": r"\bbrad smith\b",
    "Jack Clark": r"\bjack clark\b",
    "Sundar Pichai": r"\bsundar pichai\b|\bpichai\b",
    "Satya Nadella": r"\bsatya nadella\b|\bnadella\b",
    "Demis Hassabis": r"\bhassabis\b",
    "Lisa Su": r"\blisa su\b",
    "Gina Raimondo": r"\braimondo\b",
    "Mark Zuckerberg": r"\bzuckerberg\b",
    "Mira Murati": r"\bmira murati\b|\bmurati\b",
    "Greg Brockman": r"\bbrockman\b",
    "Ilya Sutskever": r"\bsutskever\b",
    "Andrej Karpathy": r"\bkarpathy\b",
    "Yann LeCun": r"\blecun\b",
    "Geoffrey Hinton": r"\bgeoffrey hinton\b|\bgeoff hinton\b",
    "Fei-Fei Li": r"\bfei-?fei li\b",
    "Arati Prabhakar": r"\bprabhakar\b",
}

# Maps a source slug to its own organization's watchlist name. A curated policy
# source naturally names itself in every event ("CSIS hosts..."), so that
# self-mention must NOT flag the event big-name (circular) -- the genuine prestige
# signal is org X appearing in ANOTHER source's event (e.g. a GWU meetup featuring
# RAND Corporation). The host's prestige is already encoded by its curated Layer-2
# status + policy-event weight. Keep this in sync when adding policy sources.
SOURCE_ORG = {
    "cset": "CSET",
    "csis": "CSIS",
    "brookings": "Brookings",
    "cnas": "CNAS",
    "atlanticcouncil": "Atlantic Council",
    "nist": "NIST",
}

# Known DC headquarters for the policy sources. Their event detail pages mostly do
# NOT expose a per-event address (only Brookings does), so when enrichment can't
# scrape a real venue we fall back to the host org's HQ -- think tanks host at
# their own building, so this is right far more often than not, and it replaces an
# unhelpful "TBD" with a real DC location. A scraped per-event address always wins.
SOURCE_HQ = {
    "csis": "CSIS, 1616 Rhode Island Ave NW, Washington, DC 20036",
    "brookings": "Brookings Institution, 1775 Massachusetts Ave NW, Washington, DC 20036",
    "cnas": "CNAS, 1701 Pennsylvania Ave NW, Washington, DC 20006",
    "atlanticcouncil": "Atlantic Council, 1400 L St NW, Washington, DC 20005",
    "cset": "CSET, Georgetown University, Washington, DC",
    "itif": "ITIF, 700 K St NW, Suite 600, Washington, DC 20001",
    "cdt": "Center for Democracy & Technology, 1401 K St NW, Suite 200, Washington, DC 20005",
    "hudson": "Hudson Institute, 1201 Pennsylvania Avenue NW, Suite 400, Washington, DC 20004",
    "aei": "American Enterprise Institute, 1789 Massachusetts Avenue NW, Washington, DC 20036",
    "bpc": "Bipartisan Policy Center, 1225 Eye Street NW, Suite 1000, Washington, DC 20005",
    "newamerica": "New America, 740 15th Street NW, Suite 900, Washington, DC 20005",
    "heritage": "The Heritage Foundation, 214 Massachusetts Ave NE, Washington, DC 20002",
    "carnegie": "Carnegie Endowment for International Peace, 1779 Massachusetts Avenue NW, Washington, DC 20036",
    "wilson": "Wilson Center, 1300 Pennsylvania Ave NW, Washington, DC 20004",
    "scsp": "Special Competitive Studies Project, 1550 Crystal Drive, Suite 500, Arlington, VA 22202",
    "stimson": "Stimson Center, 1211 Connecticut Ave NW, 8th Floor, Washington, DC 20036",
    "fas": "Federation of American Scientists, 1150 18th Street NW, Suite 1000, Washington, DC 20036",
    "mercatus": "Mercatus Center, 3434 Washington Blvd, 4th Floor, Arlington, VA 22201",
}

# DC-policy-ecosystem org names (the watchlist's institutional tier). These are
# collision-prone (short acronyms: NIST matched the tail of a line-broken
# "feminist") and appear incidentally in firehose descriptions (a careers fair
# listing "the Atlantic Council" among employers). So a match here counts as a
# big-name signal ONLY when it is in the event TITLE, or comes from a Layer-2
# curated policy source's body (a legitimate cross-mention). The lab/big-tech/
# people watchlist is unaffected (description matches there are reliable, e.g.
# AI+EXPO "exhibitors including Microsoft"). See filter._big_names.
POLICY_ORG_NAMES = {
    "CSET", "CSIS", "CNAS", "NIST", "CAISI", "RAND", "Brookings", "Atlantic Council",
}

# Watchlist entries that are PEOPLE (not orgs). Only these may flag an event as
# big-name when found among its speakers -- a speaker's employer (e.g. a panelist
# who happens to work at Microsoft) must NOT make the event a "Microsoft event".
BIG_NAME_PERSONS = {
    "Dario Amodei", "Sam Altman", "Jensen Huang", "Brad Smith", "Jack Clark",
    "Sundar Pichai", "Satya Nadella", "Demis Hassabis", "Lisa Su", "Gina Raimondo",
    "Mark Zuckerberg", "Mira Murati", "Greg Brockman", "Ilya Sutskever",
    "Andrej Karpathy", "Yann LeCun", "Geoffrey Hinton", "Fei-Fei Li", "Arati Prabhakar",
}

# DC-metro proximity. Bounding box covers DC + close NoVA + close MD suburbs.
DC_BBOX = {"lat_min": 38.70, "lat_max": 39.20, "lng_min": -77.60, "lng_max": -76.80}

# Text fallback when there is no GEO. Specific enough to avoid false hits.
DC_TEXT_PATTERN = (
    r"washington,?\s*d\.?c\.?|\bd\.c\.\b|,\s*dc\b|\bdc\s*\d{5}\b|"
    r"\barlington\b|\balexandria\b|\bmclean\b|\btysons\b|\breston\b|"
    r"\bfairfax\b|\bbethesda\b|\brockville\b|college park|silver spring|"
    r"crystal city|rosslyn|ballston|\bvirginia\b|\bmaryland\b|,\s*va\b|,\s*md\b"
)

VIRTUAL_PATTERN = r"\bvirtual\b|\bonline\b|\bwebinar\b|\bzoom\b|livestream|live stream|\bremote\b"

# Administrative / recruitment events to exclude even when they match a topic.
# These are admissions marketing (info sessions, open houses, degree-program
# promos, campus tours), not the talks / panels / workshops the aggregator is
# for. Matched against the TITLE only (descriptions carry boilerplate like
# "accelerated program" / "analytics"). Verified against live data: no real
# AI/chip event title contains these phrases, so this drops noise only.
ADMIN_EXCLUDE_PATTERN = (
    r"\binfo(?:rmation)? session\b|\bopen house\b|\bopen day\b|\bwhy gw\b|"
    r"\bmaster of\b|\bgraduate program|\bmba program|\bapplication deadline\b|"
    r"\bcommencement\b|\bnursing tour\b|\bcampus tour\b"
)

# High-volume, low-curation sources: a whole-university calendar (gwu) and a
# global org feed (aic-washington). For these, a topic mentioned only in the
# description is almost always boilerplate ("...accelerated program...",
# "...data science department..."), so require the topic in the TITLE. Curated
# Layer-2 think tanks (CSET/CSIS/Brookings) stay lenient -- their desc-only AI
# events are real (e.g. CSET "The Talent Map", "How the U.S. Wins the Global
# Tech Competition"), so a title-OR-description topic match still qualifies there.
STRICT_TITLE_TOPIC_SOURCES = {"gwu", "aic-washington", "howard", "umdcs", "gtlaw"}

# High-volume, low-curation sources: a whole-university calendar (gwu) and a
# global org feed (aic-washington). For these, a topic mentioned only in the
# description is almost always boilerplate ("...accelerated program...",
# "...data science department..."), so require the topic in the TITLE. Curated
# Layer-2 think tanks (CSET/CSIS/Brookings) stay lenient -- their desc-only AI
# events are real (e.g. CSET "The Talent Map", "How the U.S. Wins the Global
# Tech Competition"), so we keep trusting a title-OR-description match there.
STRICT_TITLE_TOPIC_SOURCES = {"gwu", "aic-washington", "howard", "umdcs", "gtlaw"}
