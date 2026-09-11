import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

# Webshare residential proxy for caption fetching (see backend/transcript.py).
# YouTube blocks/rate-limits its unofficial transcript endpoint from
# datacenter IPs (Render, AWS, GCP, ...); routing through a residential
# proxy avoids that. Optional -- if unset, transcript fetches go direct
# (fine for local/residential-IP development, not for most cloud hosts).
WEBSHARE_PROXY_USERNAME = os.environ.get("WEBSHARE_PROXY_USERNAME", "")
WEBSHARE_PROXY_PASSWORD = os.environ.get("WEBSHARE_PROXY_PASSWORD", "")

EXTRACTION_MODEL = "claude-sonnet-5"

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(ROOT_DIR / "data")))
DB_PATH = DATA_DIR / "joyofgrappling.db"
DOCS_DIR = ROOT_DIR / "docs"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Reap runtime defaults (see programs.md: Runtime Configuration) -------

DEFAULT_MAX_ITERATIONS = 8
DEFAULT_TOP_VIDEOS_PER_ITERATION = 5
DEFAULT_NOVELTY_THRESHOLD = 0.10
DEFAULT_MAX_EDGES = 200
DEFAULT_RULESET = "nogi"
DEFAULT_INCLUDE_COMPETITION_SEARCH = True
DEFAULT_LANGUAGE = "en"

WINDOW_WORD_COUNT = 300
OVERLAP_WORD_COUNT = 50

# Each search.list call costs 100 of YouTube's 10,000/day quota units, so
# this cap directly bounds daily search cost: 4/iteration x 8 iterations
# (default max_iterations) = 32 searches = 3,200 units per full run, vs.
# the prior 12/iteration cap which could burn ~9,600 units on one run.
MAX_EXPANDED_QUERIES_PER_ITERATION = 4
MAX_SEARCH_POOL_PER_QUERY = 10

# --- Authority Table (see programs.md: Authority Table) --------------------
# Matched against channel title, case-insensitive substring. First match
# wins; order matters (more specific names before generic ones).

AUTHORITY_TABLE: list[tuple[str, int]] = [
    # tier 1 -- competition footage orgs
    ("ADCC", 1),
    ("EBI", 1),
    ("Polaris", 1),
    ("UFC", 1),
    ("ONE Championship", 1),
    ("ONE FC", 1),
    # tier 2 -- world-class black belt instructional
    ("Gordon Ryan", 2),
    ("Craig Jones", 2),
    ("Danaher", 2),
    ("Galvao", 2),
    ("Buchecha", 2),
    ("Scensiki", 2),
    ("UFC BJJ", 2),
    ("Kingsway Jiu Jitsu", 2),
    ("BJJ Fanatics", 2),
    ("FloGrappling", 2),
    # tier 3 -- credentialed black belt instructional
    ("Brian Glick", 3),
    ("BJJ Scout", 3),
    ("Grapplers Guide", 3),
    ("Bernardo Faria", 3),
]

DEFAULT_TIER = 4

TIER_WEIGHTS = {1: 3.0, 2: 2.0, 3: 1.0, 4: 0.4}

# Title/description keywords that suggest footage is from live competition
# rather than an instructional -- used by score_source's
# is_competition_footage heuristic.
COMPETITION_KEYWORDS = [
    "adcc", "ebi", "polaris", "vs.", " vs ", "submission only",
    "grand prix", "trials", "finals", "match", "highlight",
]
