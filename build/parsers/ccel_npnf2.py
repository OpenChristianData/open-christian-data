"""ccel_npnf2.py
Parser for NPNF Series 2 patristic works from CCEL ThML XML.

Session 2A covers NPNF2-04 (Athanasius) and NPNF2-05 (Gregory of Nyssa).
Session 2B covers NPNF2-06 (Jerome), NPNF2-07 (Cyril of Jerusalem and
Gregory of Nazianzus), and NPNF2-08 (Basil of Caesarea). Session 2C covers
NPNF2-09 through NPNF2-14, including multi-author volumes, Gregory letters,
and the Seven Ecumenical Councils.

Parser strategy decision: use a new NPNF2 parser with shared helpers in
build/lib/ccel_thml.py. The census showed Session 2A is not just another NPNF1
batch: Athanasius is mostly one work per div1 with introduction/content div2
pairs, while Gregory groups separate works under category div1 elements and has
a bundled Letters div1. Extending ccel_npnf1.py would add series-specific config
branches to an already large parser. The shared ThML normalisation/text helpers
are reusable; the work-boundary configuration is not.

CCEL confirmed OK to parse ThML/XML (Quincy, 2026-04-01). robots.txt crawl-delay
10 was checked for this acquisition. Downloads are limited to the exact session URLs configured below.

Usage:
    py -3 build/parsers/ccel_npnf2.py --volume npnf204 --download
    py -3 build/parsers/ccel_npnf2.py --work athanasius-on-the-incarnation --parse --dry-run
    py -3 build/parsers/ccel_npnf2.py --batch 2a --parse
    py -3 build/parsers/ccel_npnf2.py --batch 2b --download
    py -3 build/parsers/ccel_npnf2.py --batch 2b --parse
    py -3 build/parsers/ccel_npnf2.py --batch 2c --parse
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request  # standards: download only
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

_BOOTSTRAP_ROOT = Path(__file__).resolve().parents[2]
if str(_BOOTSTRAP_ROOT) not in sys.path:
    sys.path.insert(0, str(_BOOTSTRAP_ROOT))

from build.lib.ccel_thml import (  # noqa: E402
    clean_text,
    count_words,
    get_all_text,
    get_scriptrefs,
    preprocess_thml,
)
from build.lib.contributors import normalize_contributors  # noqa: E402
from build.lib.schema_enums import get_enum  # noqa: E402
from build.lib.paths import REPO_ROOT  # noqa: E402

RAW_DIR = REPO_ROOT / "raw" / "ccel" / "npnf2"
OUTPUT_DIR = REPO_ROOT / "data" / "structured-text"
LOG_FILE = Path(__file__).resolve().parent / "ccel_npnf2.log"
SCHEMA_VERSION = "2.1.0"
SCRIPT_VERSION = "v1.0.0"
CRAWL_DELAY = 10
UA = "OpenChristianData/1.0 (research; open-source data project; contact: openchristiandata@gmail.com)"
SOURCE_EDITION = "Nicene and Post-Nicene Fathers, Series 2. Philip Schaff and Henry Wace (eds.)."

TRADITION_ENUM = get_enum("structured_text", "meta", "tradition")
ERA_ENUM = get_enum("structured_text", "meta", "era")
AUDIENCE_ENUM = get_enum("structured_text", "meta", "audience")
COMPLETENESS_ENUM = get_enum("structured_text", "meta", "completeness")
WORK_KIND_ENUM = get_enum("structured_text", "data", "work_kind")

ATHANASIUS = {
    "author": "Athanasius of Alexandria",
    "author_id": "athanasius-of-alexandria",
    "author_birth_year": 296,
    "author_death_year": 373,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

GREGORY_NYSSA = {
    "author": "Gregory of Nyssa",
    "author_id": "gregory-of-nyssa",
    "author_birth_year": 335,
    "author_death_year": 395,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

EUSEBIUS = {
    "author": "Eusebius of Caesarea",
    "author_id": "eusebius-of-caesarea",
    "author_birth_year": 260,
    "author_death_year": 339,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

JEROME = {
    "author": "Jerome",
    "author_id": "jerome",
    "author_birth_year": 347,
    "author_death_year": 420,
    "original_language": "lat",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

CYRIL_JERUSALEM = {
    "author": "Cyril of Jerusalem",
    "author_id": "cyril-of-jerusalem",
    "author_birth_year": 313,
    "author_death_year": 386,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

GREGORY_NAZIANZUS = {
    "author": "Gregory of Nazianzus",
    "author_id": "gregory-of-nazianzus",
    "author_birth_year": 329,
    "author_death_year": 390,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

BASIL_CAESAREA = {
    "author": "Basil of Caesarea",
    "author_id": "basil-of-caesarea",
    "author_birth_year": 330,
    "author_death_year": 379,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}


HILARY_POITIERS = {
    "author": "Hilary of Poitiers",
    "author_id": "hilary-of-poitiers",
    "author_birth_year": 310,
    "author_death_year": 368,
    "original_language": "lat",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

JOHN_DAMASCUS = {
    "author": "John of Damascus",
    "author_id": "john-of-damascus",
    "author_birth_year": 675,
    "author_death_year": 749,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical", "orthodox"],
    "era": "patristic",
    "audience": "scholarly",
}

AMBROSE_MILAN = {
    "author": "Ambrose of Milan",
    "author_id": "ambrose-of-milan",
    "author_birth_year": 339,
    "author_death_year": 397,
    "original_language": "lat",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

SULPITIUS_SEVERUS = {
    "author": "Sulpitius Severus",
    "author_id": "sulpitius-severus",
    "author_birth_year": 363,
    "author_death_year": 425,
    "original_language": "lat",
    "tradition": ["patristic"],
    "era": "patristic",
    "audience": "scholarly",
}

VINCENT_LERINS = {
    "author": "Vincent of Lerins",
    "author_id": "vincent-of-lerins",
    "author_birth_year": 380,
    "author_death_year": 445,
    "original_language": "lat",
    "tradition": ["patristic"],
    "era": "patristic",
    "audience": "scholarly",
}

JOHN_CASSIAN = {
    "author": "John Cassian",
    "author_id": "john-cassian",
    "author_birth_year": 360,
    "author_death_year": 435,
    "original_language": "lat",
    "tradition": ["patristic"],
    "era": "patristic",
    "audience": "scholarly",
}

LEO_GREAT = {
    "author": "Leo the Great",
    "author_id": "leo-the-great",
    "author_birth_year": 400,
    "author_death_year": 461,
    "original_language": "lat",
    "tradition": ["patristic", "ecumenical", "catholic"],
    "era": "patristic",
    "audience": "scholarly",
}

GREGORY_GREAT = {
    "author": "Gregory the Great",
    "author_id": "gregory-the-great",
    "author_birth_year": 540,
    "author_death_year": 604,
    "original_language": "lat",
    "tradition": ["patristic", "ecumenical", "catholic"],
    "era": "patristic",
    "audience": "scholarly",
}

ECUMENICAL_COUNCILS = {
    "author": "Seven Ecumenical Councils",
    "author_id": "ecumenical-councils",
    "author_birth_year": None,
    "author_death_year": None,
    "original_language": "grc",
    "tradition": ["patristic", "ecumenical"],
    "era": "patristic",
    "audience": "scholarly",
}

NPNF204_TRANSLATOR = "Archibald Robertson (editor and translator), 1892; Philip Schaff and Henry Wace (series editors)"
NPNF205_TRANSLATOR = "William Moore and Henry Austin Wilson (translators), 1893; Philip Schaff and Henry Wace (series editors)"
NPNF206_TRANSLATOR = "W. H. Freemantle (translator), 1892; Philip Schaff and Henry Wace (series editors)"
NPNF207_CYRIL_TRANSLATOR = "Edwin Hamilton Gifford (reviser and translator), 1893; Philip Schaff and Henry Wace (series editors)"
NPNF207_GREGORY_TRANSLATOR = "Charles Gordon Browne and James Edward Swallow (translators), 1893; Philip Schaff and Henry Wace (series editors)"
NPNF208_TRANSLATOR = "Blomfield Jackson (translator), 1895; Philip Schaff and Henry Wace (series editors)"

NPNF209_HILARY_TRANSLATOR = "E. W. Watson, L. Pullan, and others (translators), 1899; W. Sanday (editor); Philip Schaff and Henry Wace (series editors)"
NPNF209_JOHN_TRANSLATOR = "S. D. F. Salmond (translator), 1899; Philip Schaff and Henry Wace (series editors)"
NPNF210_TRANSLATOR = "H. De Romestin, E. De Romestin, and H. T. F. Duckworth (translators), 1896; Philip Schaff and Henry Wace (series editors)"
NPNF211_TRANSLATOR = "Alexander Roberts, James Donaldson, and contributors (translators/editors), 1894; Philip Schaff and Henry Wace (series editors)"
NPNF212_LEO_TRANSLATOR = "Charles Lett Feltoe (translator), 1895; Philip Schaff and Henry Wace (series editors)"
NPNF212_GREGORY_TRANSLATOR = "James Barmby (translator), 1895; Philip Schaff and Henry Wace (series editors)"
NPNF213_GREGORY_TRANSLATOR = "James Barmby (translator), 1898; Philip Schaff and Henry Wace (series editors)"
NPNF214_TRANSLATOR = "Henry R. Percival (editor and translator/compiler), 1900; Philip Schaff and Henry Wace (series editors)"


def w(slug: str, title: str, div1_id: str | None = None, *, div2_id: str | None = None,
      div_ids: list[str] | None = None, work_kind: str = "treatise",
      author: dict = ATHANASIUS, bundle_children: bool = False,
      pub_year: int | None = None, translator: str | None = None) -> dict:
    cfg = {
        "slug": slug,
        "title": title,
        "div1_id": div1_id,
        "div2_id": div2_id,
        "div_ids": div_ids,
        "work_kind": work_kind,
        "original_publication_year": pub_year,
        "completeness": "full",
        "contributors": [],
        "bundle_children": bundle_children,
        "translator": translator,
    }
    cfg.update(author)
    return cfg

VOLUME_CONFIG = {
    "npnf204": {
        "url": "https://www.ccel.org/ccel/schaff/npnf204.xml",
        "raw_file": RAW_DIR / "npnf204.xml",
        "source_edition": SOURCE_EDITION + " Vol. 4: Athanasius: Select Works and Letters. New York, 1892.",
        "translator": NPNF204_TRANSLATOR,
        "works": [
            w("athanasius-against-the-heathen", "Against the Heathen", "vi"),
            w("athanasius-on-the-incarnation", "On the Incarnation of the Word", "vii"),
            w("athanasius-deposition-of-arius", "Deposition of Arius", "viii"),
            w("eusebius-letter-on-nicene-creed", "Letter of Eusebius on the Nicene Creed", "ix", author=EUSEBIUS),
            w("athanasius-statement-of-faith", "Statement of Faith", "x"),
            w("athanasius-on-luke-10-22", "On Luke 10:22", "xi"),
            w("athanasius-encyclical-letter", "Encyclical Letter", "xii"),
            w("athanasius-defence-against-the-arians", "Defence Against the Arians", "xiii"),
            w("athanasius-defence-of-the-nicene-definition", "Defence of the Nicene Definition", "xiv"),
            w("athanasius-defence-of-dionysius", "Defence of Dionysius", "xv"),
            w("athanasius-life-of-antony", "Life of Antony", "xvi", work_kind="devotional-classic"),
            w("athanasius-circular-to-bishops-of-egypt-and-libya", "Circular to Bishops of Egypt and Libya", "xvii"),
            w("athanasius-apology-to-the-emperor", "Apology to the Emperor", "xviii"),
            w("athanasius-defence-of-his-flight", "Defence of His Flight", "xix"),
            w("athanasius-arian-history", "Arian History", "xx", work_kind="church-history"),
            w("athanasius-against-the-arians", "Against the Arians", "xxi"),
            w("athanasius-on-ariminum-and-seleucia", "On the Councils of Ariminum and Seleucia", "xxii"),
            w("athanasius-synodal-letter-to-antioch", "Synodal Letter to the People of Antioch", "xxiii"),
            w("athanasius-synodal-letter-to-africa", "Synodal Letter to the Bishops of Africa", "xxiv"),
            w("athanasius-letters-and-chronicles", "Letters of Athanasius with Ancient Chronicles", "xxv", bundle_children=True),
        ],
    },
    "npnf205": {
        "url": "https://www.ccel.org/ccel/schaff/npnf205.xml",
        "raw_file": RAW_DIR / "npnf205.xml",
        "source_edition": SOURCE_EDITION + " Vol. 5: Gregory of Nyssa: Dogmatic Treatises, etc. New York, 1893.",
        "translator": NPNF205_TRANSLATOR,
        "works": [
            w("gregory-of-nyssa-against-eunomius", "Against Eunomius", "viii", div2_id="viii.i", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-answer-to-eunomius-second-book", "Answer to Eunomius' Second Book", "viii", div2_id="viii.ii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-the-holy-spirit", "On the Holy Spirit", "viii", div2_id="viii.iii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-the-holy-trinity", "On the Holy Trinity and the Godhead of the Holy Spirit", "viii", div2_id="viii.iv", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-not-three-gods", "On Not Three Gods", "viii", div2_id="viii.v", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-the-faith", "On the Faith", "viii", div2_id="viii.vi", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-virginity", "On Virginity", "ix", div2_id="ix.ii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-infants-early-deaths", "On Infants' Early Deaths", "ix", div2_id="ix.iii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-pilgrimages", "On Pilgrimages", "ix", div2_id="ix.iv", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-the-making-of-man", "On the Making of Man", "x", div2_id="x.ii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-the-soul-and-resurrection", "On the Soul and the Resurrection", "x", div2_id="x.iii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-great-catechism", "The Great Catechism", "xi", div2_id="xi.ii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-funeral-oration-on-meletius", "Funeral Oration on Meletius", "xii", div2_id="xii.ii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-on-the-baptism-of-christ", "On the Baptism of Christ", "xii", div2_id="xii.iii", author=GREGORY_NYSSA),
            w("gregory-of-nyssa-letters", "Letters", "xiii", author=GREGORY_NYSSA, bundle_children=True),
        ],
    },
    "npnf206": {
        "url": "https://www.ccel.org/ccel/schaff/npnf206.xml",
        "raw_file": RAW_DIR / "npnf206.xml",
        "source_edition": SOURCE_EDITION + " Vol. 6: Jerome: The Principal Works of St. Jerome. New York, 1892.",
        "translator": NPNF206_TRANSLATOR,
        "works": [
            w("jerome-letters", "Letters", "v", author=JEROME, bundle_children=True, work_kind="theological-work", pub_year=1892),
            w("jerome-life-of-paulus", "The Life of Paulus the First Hermit", "vi", div2_id="vi.i", author=JEROME, work_kind="devotional-classic", pub_year=1892),
            w("jerome-life-of-hilarion", "The Life of S. Hilarion", "vi", div2_id="vi.ii", author=JEROME, work_kind="devotional-classic", pub_year=1892),
            w("jerome-life-of-malchus", "The Life of Malchus, the Captive Monk", "vi", div2_id="vi.iii", author=JEROME, work_kind="devotional-classic", pub_year=1892),
            w("jerome-dialogue-against-luciferians", "The Dialogue Against the Luciferians", "vi", div2_id="vi.iv", author=JEROME, pub_year=1892),
            w("jerome-perpetual-virginity-of-mary", "The Perpetual Virginity of Blessed Mary", "vi", div2_id="vi.v", author=JEROME, pub_year=1892),
            w("jerome-against-jovinianus", "Against Jovinianus", "vi", div2_id="vi.vi", author=JEROME, pub_year=1892),
            w("jerome-against-vigilantius", "Against Vigilantius", "vi", div2_id="vi.vii", author=JEROME, pub_year=1892),
            w("jerome-to-pammachius-against-john-of-jerusalem", "To Pammachius Against John of Jerusalem", "vi", div2_id="vi.viii", author=JEROME, pub_year=1892),
            w("jerome-against-pelagians", "Against the Pelagians", "vi", div2_id="vi.ix", author=JEROME, pub_year=1892),
        ],
    },
    "npnf207": {
        "url": "https://www.ccel.org/ccel/schaff/npnf207.xml",
        "raw_file": RAW_DIR / "npnf207.xml",
        "source_edition": SOURCE_EDITION + " Vol. 7: Cyril of Jerusalem and Gregory Nazianzen. New York, 1893.",
        "translator": NPNF207_CYRIL_TRANSLATOR,
        "works": [
            w("cyril-of-jerusalem-catechetical-lectures", "Catechetical Lectures", "ii", author=CYRIL_JERUSALEM, bundle_children=True, work_kind="theological-work", pub_year=1893, translator=NPNF207_CYRIL_TRANSLATOR),
            w("gregory-of-nazianzus-select-orations", "Select Orations", "iii", author=GREGORY_NAZIANZUS, bundle_children=True, work_kind="theological-work", pub_year=1893, translator=NPNF207_GREGORY_TRANSLATOR),
            w("gregory-of-nazianzus-select-letters", "Select Letters", "iv", author=GREGORY_NAZIANZUS, bundle_children=True, work_kind="theological-work", pub_year=1893, translator=NPNF207_GREGORY_TRANSLATOR),
        ],
    },

    "npnf208": {
        "url": "https://www.ccel.org/ccel/schaff/npnf208.xml",
        "raw_file": RAW_DIR / "npnf208.xml",
        "source_edition": SOURCE_EDITION + " Vol. 8: Basil: Letters and Select Works. Edinburgh, 1895.",
        "translator": NPNF208_TRANSLATOR,
        "works": [
            w("basil-of-caesarea-on-the-holy-spirit", "On the Holy Spirit", "vii", author=BASIL_CAESAREA, bundle_children=True, pub_year=1895),
            w("basil-of-caesarea-hexaemeron", "The Hexaemeron", "viii", author=BASIL_CAESAREA, bundle_children=True, work_kind="theological-work", pub_year=1895),
            w("basil-of-caesarea-letters", "Letters", "ix", author=BASIL_CAESAREA, bundle_children=True, work_kind="theological-work", pub_year=1895),
        ],
    },
    "npnf209": {
        "url": "https://www.ccel.org/ccel/schaff/npnf209.xml",
        "raw_file": RAW_DIR / "npnf209.xml",
        "source_edition": SOURCE_EDITION + " Vol. 9: Hilary of Poitiers and John of Damascus. Edinburgh, 1899.",
        "translator": NPNF209_HILARY_TRANSLATOR,
        "works": [
            w("hilary-of-poitiers-select-works", "Select Works", "ii", author=HILARY_POITIERS, bundle_children=True, pub_year=1899, translator=NPNF209_HILARY_TRANSLATOR),
            w("john-of-damascus-orthodox-faith", "Exposition of the Orthodox Faith", "iii", author=JOHN_DAMASCUS, bundle_children=True, pub_year=1899, translator=NPNF209_JOHN_TRANSLATOR),
        ],
    },
    "npnf210": {
        "url": "https://www.ccel.org/ccel/schaff/npnf210.xml",
        "raw_file": RAW_DIR / "npnf210.xml",
        "source_edition": SOURCE_EDITION + " Vol. 10: Ambrose: Select Works and Letters. Edinburgh, 1896.",
        "translator": NPNF210_TRANSLATOR,
        "works": [
            w("ambrose-of-milan-on-duties-of-clergy", "On the Duties of the Clergy", "iv", div2_id="iv.i", author=AMBROSE_MILAN, pub_year=1896),
            w("ambrose-of-milan-on-holy-spirit", "On the Holy Spirit", "iv", div2_id="iv.ii", author=AMBROSE_MILAN, pub_year=1896),
            w("ambrose-of-milan-on-satyrus", "On the Decease of His Brother Satyrus", "iv", div2_id="iv.iii", author=AMBROSE_MILAN, work_kind="devotional-classic", pub_year=1896),
            w("ambrose-of-milan-exposition-of-christian-faith", "Exposition of the Christian Faith", "iv", div2_id="iv.iv", author=AMBROSE_MILAN, pub_year=1896),
            w("ambrose-of-milan-on-mysteries", "On the Mysteries", "iv", div2_id="iv.v", author=AMBROSE_MILAN, pub_year=1896),
            w("ambrose-of-milan-concerning-repentance", "Concerning Repentance", "iv", div2_id="iv.vi", author=AMBROSE_MILAN, pub_year=1896),
            w("ambrose-of-milan-concerning-virgins", "Concerning Virgins", "iv", div2_id="iv.vii", author=AMBROSE_MILAN, work_kind="devotional-classic", pub_year=1896),
            w("ambrose-of-milan-concerning-widows", "Concerning Widows", "iv", div2_id="iv.viii", author=AMBROSE_MILAN, work_kind="devotional-classic", pub_year=1896),
            w("ambrose-of-milan-letters", "Selections from the Letters", "v", author=AMBROSE_MILAN, bundle_children=True, work_kind="theological-work", pub_year=1896),
        ],
    },
    "npnf211": {
        "url": "https://www.ccel.org/ccel/schaff/npnf211.xml",
        "raw_file": RAW_DIR / "npnf211.xml",
        "source_edition": SOURCE_EDITION + " Vol. 11: Sulpitius Severus, Vincent of Lerins, John Cassian. Edinburgh, 1894.",
        "translator": NPNF211_TRANSLATOR,
        "works": [
            w("sulpitius-severus-selected-works", "Selected Works", "ii", author=SULPITIUS_SEVERUS, bundle_children=True, work_kind="church-history", pub_year=1894),
            w("vincent-of-lerins-commonitory", "Commonitory", "iii", author=VINCENT_LERINS, bundle_children=True, pub_year=1894),
            w("john-cassian-selected-works", "Selected Works", "iv", author=JOHN_CASSIAN, bundle_children=True, work_kind="devotional-classic", pub_year=1894),
        ],
    },
    "npnf212": {
        "url": "https://www.ccel.org/ccel/schaff/npnf212.xml",
        "raw_file": RAW_DIR / "npnf212.xml",
        "source_edition": SOURCE_EDITION + " Vol. 12: Leo the Great and Gregory the Great. Edinburgh, 1895.",
        "translator": NPNF212_LEO_TRANSLATOR,
        "works": [
            w("leo-the-great-letters-and-sermons", "Letters and Sermons", "ii", author=LEO_GREAT, bundle_children=True, work_kind="theological-work", pub_year=1895, translator=NPNF212_LEO_TRANSLATOR),
            w("gregory-the-great-pastoral-rule-and-epistles", "Pastoral Rule and Selected Epistles", "iii", author=GREGORY_GREAT, bundle_children=True, work_kind="devotional-classic", pub_year=1895, translator=NPNF212_GREGORY_TRANSLATOR),
        ],
    },
    "npnf213": {
        "url": "https://www.ccel.org/ccel/schaff/npnf213.xml",
        "raw_file": RAW_DIR / "npnf213.xml",
        "source_edition": SOURCE_EDITION + " Vol. 13: Gregory the Great II, Ephraim Syrus, Aphrahat. Edinburgh, 1898.",
        "translator": NPNF213_GREGORY_TRANSLATOR,
        "works": [
            w("gregory-the-great-selected-epistles", "Selected Epistles", "ii", author=GREGORY_GREAT, bundle_children=True, work_kind="theological-work", pub_year=1898),
        ],
    },
    "npnf214": {
        "url": "https://www.ccel.org/ccel/schaff/npnf214.xml",
        "raw_file": RAW_DIR / "npnf214.xml",
        "source_edition": SOURCE_EDITION + " Vol. 14: The Seven Ecumenical Councils. Edinburgh, 1900.",
        "translator": NPNF214_TRANSLATOR,
        "works": [
            w("ecumenical-councils-canons-and-decrees", "The Seven Ecumenical Councils: Canons and Decrees", div_ids=["vii", "ix", "x", "xi", "xii", "xiii", "xvi"], author=ECUMENICAL_COUNCILS, bundle_children=True, work_kind="theological-work", pub_year=1900),
        ],
    },

}
BATCH_2A_VOLS = ["npnf204", "npnf205"]
BATCH_2B_VOLS = ["npnf206", "npnf207", "npnf208"]
BATCH_2C_VOLS = ["npnf209", "npnf210", "npnf211", "npnf212", "npnf213", "npnf214"]

_HEADING_TAGS = frozenset(["h1", "h2", "h3", "h4", "title"])
_SKIP_TAGS = frozenset(["note", "pb", "insertIndex", "style", "selector", "scripContext"])
_DIV_TAG_RE = re.compile(r"^div\d?$")
_EDITORIAL_TITLE_PATTERNS = re.compile(
    r"^(title page|second title page|preface|editor|editorial preface|introduction|"
    r"prolegomena|indexes?|index of|greek words|appendix|excursus|additional note|"
    r"note|prefatory note|introductory note|historical introduction|general introduction|"
    r"general literature|regula pastoralis|registrum epistolarum|life and writings|"
    r"works on analytical|dates of treatises|chronology and tables)\b",
    re.IGNORECASE,
)
_EDITORIAL_DIV_TYPES = frozenset(["Preface", "Table of Contents"])
_CONTENT_DIV_TYPES = frozenset(["Book", "Chapter", "Section", "Letter", "Homily", "Sermon", "Tractate", "Division", "Dialogue", "Demonstration"])
_DIV_TYPE_MAP = {
    "Book": "book",
    "Chapter": "chapter",
    "Section": "section",
    "Letter": "letter",
    "Homily": "chapter",
    "Sermon": "chapter",
    "Tractate": "chapter",
    "Division": "book",
    "Dialogue": "chapter",
    "Demonstration": "chapter",
    "Note": None,
    "Table": None,
}


def validate_work_configs() -> None:
    for vol_id, vol_cfg in VOLUME_CONFIG.items():
        for cfg in vol_cfg["works"]:
            slug = cfg["slug"]
            for tradition in cfg.get("tradition", []):
                assert tradition in TRADITION_ENUM, f"{slug}: invalid tradition {tradition!r}"
            assert cfg["era"] in ERA_ENUM, f"{slug}: invalid era {cfg['era']!r}"
            assert cfg["audience"] in AUDIENCE_ENUM, f"{slug}: invalid audience {cfg['audience']!r}"
            assert cfg["completeness"] in COMPLETENESS_ENUM, f"{slug}: invalid completeness {cfg['completeness']!r}"
            assert cfg["work_kind"] in WORK_KIND_ENUM, f"{slug}: invalid work_kind {cfg['work_kind']!r}"
        assert vol_id in BATCH_2A_VOLS + BATCH_2B_VOLS + BATCH_2C_VOLS


validate_work_configs()


def download_volume(vol_id: str, force: bool = False) -> None:
    cfg = VOLUME_CONFIG[vol_id]
    dest = cfg["raw_file"]
    if dest.exists() and dest.stat().st_size > 0 and not force:
        print(f"  Cached: {dest.name} ({dest.stat().st_size // 1024} KB)")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(cfg["url"], headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = resp.read()
    dest.write_bytes(data)
    print(f"  Downloaded {dest.name} ({len(data) // 1024} KB)")


def is_editorial_div(elem) -> bool:
    div_type = elem.get("type", "")
    if div_type in _CONTENT_DIV_TYPES:
        return False
    if div_type in _EDITORIAL_DIV_TYPES:
        return True
    title = clean_text(elem.get("title", ""))
    return bool(title and _EDITORIAL_TITLE_PATTERNS.match(title))


def get_div_label_title(elem) -> tuple[str | None, str | None]:
    n_value = clean_text(elem.get("n", ""))
    div_type = clean_text(elem.get("type", ""))
    title = clean_text(elem.get("title", ""))
    label = f"{div_type} {n_value}" if div_type and n_value else n_value
    if title and label and title.lower().startswith(label.lower()):
        title = title[len(label):].strip().lstrip(".").strip()
    if not title:
        for child in elem:
            if child.tag in _HEADING_TAGS:
                title = clean_text(get_all_text(child))
                if title:
                    break
    return label or None, title or None


def collect_content_blocks(elem) -> list[str]:
    blocks: list[str] = []
    for child in elem:
        if child.tag in _HEADING_TAGS or child.tag in _SKIP_TAGS or _DIV_TAG_RE.match(child.tag):
            continue
        if child.tag in ("p", "argument", "q"):
            text = clean_text(get_all_text(child))
            if text:
                blocks.append(text)
        elif child.tag in ("ul", "ol"):
            items = [clean_text(get_all_text(li)) for li in child.findall("li")]
            items = [item for item in items if item]
            if items:
                blocks.append("; ".join(items))
    return blocks


def parse_div_recursive(elem, max_depth: int = 5, depth: int = 0) -> dict | None:
    if is_editorial_div(elem):
        return None
    div_type = elem.get("type", "")
    section_type = _DIV_TYPE_MAP.get(div_type)
    if div_type and section_type is None and div_type in ("Note", "Table"):
        return None
    if section_type is None:
        section_type = "section" if depth > 0 else "book"
    label, title = get_div_label_title(elem)
    content_blocks = collect_content_blocks(elem)
    children = []
    if depth < max_depth:
        for child in elem:
            if not _DIV_TAG_RE.match(child.tag):
                continue
            result = parse_div_recursive(child, max_depth=max_depth, depth=depth + 1)
            if result is not None:
                children.append(result)
    if not content_blocks and not children:
        return None
    return {
        "section_type": section_type,
        "label": label,
        "title": title,
        "content_blocks": content_blocks,
        "scripture_references": get_scriptrefs(elem),
        "word_count": count_words(content_blocks),
        "children": children,
    }


def direct_div_children(elem) -> list:
    return [child for child in elem if _DIV_TAG_RE.match(child.tag)]


def parse_container(container, *, bundle_children: bool) -> list[dict]:
    child_divs = direct_div_children(container)
    if bundle_children or child_divs:
        sections = []
        for child in child_divs:
            result = parse_div_recursive(child, depth=0)
            if result is not None:
                sections.append(result)
        if sections:
            return sections
    result = parse_div_recursive(container, depth=0)
    return [result] if result is not None else []


def find_work_container(body, work_cfg: dict):
    div1 = None
    for child in body:
        if _DIV_TAG_RE.match(child.tag) and child.get("id") == work_cfg["div1_id"]:
            div1 = child
            break
    if div1 is None:
        raise RuntimeError(f"div1 id={work_cfg['div1_id']!r} not found")
    div2_id = work_cfg.get("div2_id")
    if not div2_id:
        return div1
    for child in div1:
        if _DIV_TAG_RE.match(child.tag) and child.get("id") == div2_id:
            return child
    raise RuntimeError(f"div2 id={div2_id!r} not found in div1 {work_cfg['div1_id']!r}")


def find_work_containers(body, work_cfg: dict) -> list:
    div_ids = work_cfg.get("div_ids")
    if not div_ids:
        return [find_work_container(body, work_cfg)]
    containers = []
    for div_id in div_ids:
        for child in body:
            if _DIV_TAG_RE.match(child.tag) and child.get("id") == div_id:
                containers.append(child)
                break
        else:
            raise RuntimeError(f"div id={div_id!r} not found")
    return containers


def parse_volume_work(vol_id: str, work_cfg: dict, raw_bytes: bytes) -> dict:
    source_hash = "sha256:" + hashlib.sha256(raw_bytes).hexdigest()
    root = ET.fromstring(preprocess_thml(raw_bytes))
    body = root.find("ThML.body")
    if body is None:
        raise RuntimeError(f"No ThML.body in {vol_id}")
    sections = []
    for container in find_work_containers(body, work_cfg):
        sections.extend(parse_container(container, bundle_children=work_cfg.get("bundle_children", False)))
    return {"work_id": work_cfg["slug"], "sections": sections, "_source_hash": source_hash}


def sum_tree(sections: list[dict], key: str) -> int:
    total = 0
    for section in sections:
        total += section.get(key, 0)
        total += sum_tree(section.get("children", []), key)
    return total


def count_nodes(sections: list[dict]) -> int:
    return sum(1 + count_nodes(section.get("children", [])) for section in sections)


def walk_sections(sections: list[dict]):
    for section in sections:
        yield section
        yield from walk_sections(section.get("children", []))


def build_meta(vol_id: str, work_cfg: dict, source_hash: str) -> dict:
    vol_cfg = VOLUME_CONFIG[vol_id]
    raw_file = vol_cfg["raw_file"]
    mtime = datetime.fromtimestamp(raw_file.stat().st_mtime, tz=timezone.utc)
    return {
        "id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_id": work_cfg["author_id"],
        "author_birth_year": work_cfg["author_birth_year"],
        "author_death_year": work_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("original_publication_year"),
        "language": "en",
        "original_language": work_cfg["original_language"],
        "tradition": work_cfg["tradition"],
        "tradition_notes": "",
        "era": work_cfg["era"],
        "audience": work_cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "schema_version": SCHEMA_VERSION,
        "completeness": work_cfg["completeness"],
        "provenance": {
            "source_url": vol_cfg["url"],
            "source_format": "ThML XML",
            "source_edition": vol_cfg["source_edition"],
            "download_date": mtime.strftime("%Y-%m-%d"),
            "source_hash": source_hash,
            "processing_method": "automated",
            "processing_script_version": f"build/parsers/ccel_npnf2.py@{SCRIPT_VERSION}",
            "processing_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "notes": "ThML entities normalised; DOCTYPE stripped; footnotes, page breaks, and editorial front matter excluded.",
            "source_type": "ccel_thml",
            "source_file": str(raw_file.relative_to(REPO_ROOT)).replace("\\", "/"),
            "translator": work_cfg.get("translator") or vol_cfg["translator"],
        },
    }


def write_source_config(vol_id: str, work_cfg: dict, source_hash: str) -> None:
    vol_cfg = VOLUME_CONFIG[vol_id]
    config_dir = REPO_ROOT / "sources" / "structured-text" / work_cfg["slug"]
    config_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "resource_id": work_cfg["slug"],
        "title": work_cfg["title"],
        "author": work_cfg["author"],
        "author_id": work_cfg["author_id"],
        "author_birth_year": work_cfg["author_birth_year"],
        "author_death_year": work_cfg["author_death_year"],
        "contributors": normalize_contributors(work_cfg.get("contributors", [])),
        "original_publication_year": work_cfg.get("original_publication_year"),
        "language": "en",
        "original_language": work_cfg["original_language"],
        "tradition": work_cfg["tradition"],
        "era": work_cfg["era"],
        "audience": work_cfg["audience"],
        "license": "public-domain",
        "schema_type": "structured_text",
        "work_kind": work_cfg["work_kind"],
        "source_url": vol_cfg["url"],
        "source_format": "ThML XML",
        "source_edition": vol_cfg["source_edition"],
        "source_hash": source_hash,
        "source_type": "ccel_thml",
        "source_file": str(vol_cfg["raw_file"].relative_to(REPO_ROOT)).replace("\\", "/"),
        "translator": work_cfg.get("translator") or vol_cfg["translator"],
        "download_date": datetime.fromtimestamp(vol_cfg["raw_file"].stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d"),
        "output_file": f"data/structured-text/{work_cfg['slug']}.json",
        "clearance_date": "2026-04-01",
        "notes": "CCEL confirmed OK to parse. Crawl-delay 10s observed for downloads. License: Public Domain.",
    }
    path = config_dir / "config.json"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(config, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def selected_volumes(args) -> list[str]:
    if args.volume:
        return [args.volume]
    if args.batch == "2a":
        return BATCH_2A_VOLS
    if args.batch == "2b":
        return BATCH_2B_VOLS
    if args.batch == "2c":
        return BATCH_2C_VOLS
    return list(VOLUME_CONFIG)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse NPNF Series 2 CCEL ThML works")
    parser.add_argument("--volume", choices=list(VOLUME_CONFIG), default=None)
    parser.add_argument("--work", default=None)
    parser.add_argument("--batch", choices=["2a", "2b", "2c"], default=None)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--parse", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        args.parse = True
    if not args.download and not args.parse:
        parser.print_help()
        return
    logs: list[str] = []
    errors = 0
    written = 0

    def log(message: str) -> None:
        print(message.encode("ascii", errors="replace").decode("ascii"))
        logs.append(message)

    vols = selected_volumes(args)
    log(f"NPNF2 parser {SCRIPT_VERSION}: volumes={vols} download={args.download} parse={args.parse} dry_run={args.dry_run}")
    if args.download:
        for index, vol_id in enumerate(vols):
            if index:
                time.sleep(CRAWL_DELAY)
            try:
                download_volume(vol_id, force=args.force)
            except Exception as exc:
                log(f"ERROR download {vol_id}: {exc}")
                errors += 1
    if args.parse:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for vol_id in vols:
            vol_cfg = VOLUME_CONFIG[vol_id]
            raw_file = vol_cfg["raw_file"]
            if not raw_file.exists() or raw_file.stat().st_size == 0:
                log(f"ERROR raw file missing or empty: {raw_file}")
                errors += 1
                continue
            raw_bytes = raw_file.read_bytes()
            works = vol_cfg["works"]
            if args.work:
                works = [cfg for cfg in works if cfg["slug"] == args.work]
            for work_cfg in works:
                try:
                    result = parse_volume_work(vol_id, work_cfg, raw_bytes)
                except Exception as exc:
                    log(f"ERROR parse {work_cfg['slug']}: {exc}")
                    errors += 1
                    continue
                top_sections = len(result["sections"])
                total_nodes = count_nodes(result["sections"])
                total_words = sum_tree(result["sections"], "word_count")
                log(f"{work_cfg['slug']}: {top_sections} top sections, {total_nodes} nodes, {total_words} words")
                if top_sections == 0 or total_words == 0:
                    errors += 1
                    log(f"ERROR empty output: {work_cfg['slug']}")
                    continue
                if args.dry_run:
                    continue
                output = {
                    "meta": build_meta(vol_id, work_cfg, result["_source_hash"]),
                    "data": {
                        "work_id": result["work_id"],
                        "work_kind": work_cfg["work_kind"],
                        "sections": result["sections"],
                    },
                }
                out_path = OUTPUT_DIR / f"{work_cfg['slug']}.json"
                with out_path.open("w", encoding="utf-8", newline="\n") as fh:
                    json.dump(output, fh, ensure_ascii=False, indent=2)
                    fh.write("\n")
                write_source_config(vol_id, work_cfg, result["_source_hash"])
                written += 1
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(logs) + "\n")
    log(f"Done. Files written: {written}. Errors: {errors}.")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

