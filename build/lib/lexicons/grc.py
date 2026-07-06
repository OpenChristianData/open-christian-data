"""Greek seed lexicon for historical/OCR review dispatch plus Layer 2 vocabulary."""

from __future__ import annotations


COVERAGE_STATUS = "seed_only"

ARCHAIC_FORMS: dict[str, str] = {
    "ϲ": "σ",
    "Ϲ": "Σ",
    "Ιηϲουϲ": "Ιησους",
    "Χριϲτοϲ": "Χριστος",
    "θεοϲ": "θεος",
    "κυριοϲ": "κυριος",
    "αντιλεγομενα": "ἀντιλεγόμενα",
    "εκκληϲια": "εκκλησια",
    "αποϲτολοϲ": "αποστολος",
    "πνευμα": "πνεῦμα",
    "λογοϲ": "λογος",
    "κοϲμοϲ": "κοσμος",
}

# Layer 2 vocabulary — transliterated Greek theological terms in Latin script.
# These are the surface forms used in 19th-century English and German scholarship
# when Greek terms are printed in transliteration. Distinct from native-script
# Greek (handled by Layer 1) — Layer 2 disambiguates Latin-script blocks that
# contain Greek loanwords.
VOCAB: frozenset[str] = frozenset({
    # R55 fixture tokens (in transliteration)
    "logos", "agape", "agapē", "pneuma", "ekklesia", "ekklēsia", "kurios",
    "christos", "parousia", "diatheke", "diathēkē", "didache", "didachē",
    "kerygma", "kērygma",
    # Core transliterated Greek theological vocabulary
    "pistis", "elpis", "charis", "soteria", "sōtēria", "koine", "koinē",
    "theos", "kyrios", "baptisma", "evangelion", "euaggelion", "euangelion",
    "apostolos", "prophetes", "prophētēs", "angelos", "daimon", "daimōn",
    "sarx", "soma", "sōma", "psyche", "psychē", "nous", "zoe", "zōē",
    "thanatos", "anastasis", "krisis", "dikaiosyne", "dikaiosynē",
    "hamartia", "metanoia", "aletheia", "alētheia", "doxa", "chara",
    "eirene", "eirēnē", "dynamis", "mysterion", "mystērion", "kairos",
    "kronos", "chronos", "eschaton", "pleroma", "plērōma", "telos",
    "archon", "archōn", "aion", "aiōn", "kosmos", "physis", "pneumatikos",
    "sarkikos", "doxologia", "doxology", "eucharistia", "eucharist",
    "baptismos", "katabasis", "anabasis", "paroikos", "paroikia",
    "ekklesiologia", "christologia", "pneumatologia", "soteriologia",
    "eschatologia", "theodicy", "theopneustos", "koinonia", "koinōnia",
    "agape", "eros", "philia", "storge", "philanthropy", "anthropology",
    "cosmology", "logikos", "logismos", "logion", "theologia", "theonomos",
    "theophany", "theosis", "theōsis", "theophagy", "theandrism",
    "perichoresis", "perichōrēsis", "hypostasis", "ousia", "homoousios",
    "homoiousios", "prosopon", "prosōpon", "energeia", "synergeia",
    "synodical", "synoptikon", "synoptika", "apokatastasis", "apokalypsis",
    "apocalypse", "apocrypha", "apocryphal", "gnosis", "gnōsis", "gnostic",
    "gnosticism", "epignosis", "epignōsis", "pronoia", "oikonomia",
    "oikumene", "ekumene", "ecumene", "oikoumene", "pantos", "pantokrator",
    "sebastos", "augustus", "doxastikos", "doxazein", "episkopoi",
    "episkopos", "presbyteros", "diakonos", "laos", "laikos", "kleros",
    "klēros", "charismata", "charisma", "glossolalia", "propheteia",
    "prophēteia", "diakonia", "martyria", "leiturgia", "leitourgia",
    "liturgy", "anamnesis", "epiclesis", "kenosis", "kenōsis", "plerosis",
    "apotheosis",
    # Proper names in Greek transliteration
    "Origenes", "Irenaeus", "Tertullianus", "Athanasius", "Alexandros",
    "Basilios", "Gregorios", "Chrysostomos", "Ioannes", "Iōannēs", "Matthias",
    "Markos", "Loukas", "Paulos", "Petros", "Andreas", "Philippos",
    "Bartholomaios", "Thaddaios", "Silas", "Timotheos", "Titus", "Philemon",
    "Barnabas", "Eusebios", "Klemes", "Polykarpos", "Ignatios",
    # Variants and extra forms
    "pater", "huios", "pneumatikon", "psychikon", "anthropos", "anthrōpos",
    "anthropoi", "andron", "andrōn", "gyne", "gynē", "gynaika",
    "soter", "sōtēr", "soteria", "didaskalos", "rabbi", "rabbouni",
    "messianos", "messias", "iesous", "iēsous", "christianos", "christianoi",
    "ethnos", "ethnē", "ioudaios", "ioudaioi", "hellenes", "hellēnes",
    "hellenistai", "hellēnistai",
    # Greek terms in scholarly Latin script
    "theos", "theou", "theō", "theon", "theoi", "theōn", "kyrios", "kyriou",
    "kyriō", "kyrion", "iesous", "iesou", "iesoun", "christos", "christou",
    "christō", "christon", "pneuma", "pneumatos", "pneumati", "pneumata",
    "logos", "logou", "logō", "logon", "logoi", "logōn",
    # Liturgical Greek transliterations
    "kyrie", "kyrieleison", "christeleison", "trisagion", "anaphora",
    "epiklesis", "epiklēsis", "diptychs", "antiphon", "antiphōn",
    "troparion", "kontakion", "kanon", "katavasia", "irmos",
    "doxology", "trisagion", "cheroubikon", "axion", "estin",
    # More Greek vocabulary in transliteration
    "agathos", "agathē", "agathon", "kakos", "kakē", "kakon",
    "kalos", "kalē", "kalon", "aischros", "aischrā", "aischron",
    "alethes", "alēthēs", "pseudes", "pseudos", "dikaios", "dikaia",
    "dikaion", "adikia", "hagios", "hagia", "hagion", "hieros", "hiera",
    "hieron", "kainos", "kainē", "kainon", "palaios", "palaia", "palaion",
    "neos", "nea", "neon", "geraios", "geraion",
    # Verb forms
    "egeiro", "egeirō", "anistēmi", "anastasis", "pisteuō", "pistis",
    "agapao", "agapaō", "agape", "elpizō", "elpis", "phileō", "philia",
    "ginōskō", "gnōsis", "horao", "horaō", "akouō", "akoē", "lego",
    "legō", "logos", "lalō", "lalia", "graphō", "graphē", "anagignōskō",
    "didasko", "didaskō", "didache", "matheteuō", "mathetes", "mathētēs",
    "baptizo", "baptizō", "baptisma", "katharizo", "katharizō", "katharos",
    "hagiazo", "hagiazō", "hagiasmos", "doxazo", "doxazō", "doxa",
    # Cosmos, creation, eschatology
    "ktisis", "ktiseos", "ktiseōs", "kosmos", "aiōn", "aiōnes",
    "ouranos", "ouranoi", "ouranon", "ge", "gē", "ges", "gēs",
    "abyssos", "thalassa", "potamos", "helios", "hēlios", "selene",
    "selēnē", "aster", "astēr", "asteres", "asteres",
    # Numbers
    "heis", "mia", "hen", "duo", "treis", "tria", "tessares", "pente",
    "hex", "hepta", "okto", "oktō", "ennea", "deka", "hekaton",
    "chilias", "chilioi", "myrias", "myrioi",
    # Time, place
    "chronos", "kairos", "aion", "aiōn", "hēmera", "hemera", "nyx",
    "nyks", "ōra", "hōra", "month", "men", "mēn", "etos", "etē",
    "topos", "kosmos", "polis", "ethnos", "patris", "patrida",
    "oikos", "naos", "hieron", "synagoge", "synagōgē", "ekklesia",
    # Sacraments and church life
    "eucharistia", "anaphora", "anamnesis", "anamnēsis", "epiklesis",
    "diakonia", "leitourgia", "homilia", "katechesis", "katēchēsis",
    "katechumenos", "katēchoumenos", "presbyterion", "diakonion",
    "episkopaton", "patriarchēs", "patriarchatos", "metropolitēs",
    "archiepiskopos", "archimandrites", "archimandritēs", "hegumenos",
    "hēgoumenos", "monachos", "monastērion", "monastiriou", "askesis",
    "askēsis", "asketēs", "asketai",
    # Greek prepositions and particles (in transliteration)
    "ek", "eis", "epi", "para", "peri", "syn", "sun", "pro", "anti",
    "dia", "kata", "meta", "hyper", "hypo", "apo", "en",
    "men", "de", "gar", "oun", "alla", "kai", "te", "kai", "hina",
    "hoti", "hopōs", "hōs", "an", "ean", "ei",
    # More theological terms
    "sphragis", "sphragizo", "sphragizō", "myron", "chrisma", "chrismata",
    "anointing", "unction", "imposition", "ordination", "consecration",
    "exorcism", "exorkismos", "exorkistēs",
    # Patristic vocabulary
    "patristic", "patristikos", "patrologia", "patrologium",
    "synodos", "synodikon", "oikoumenikos", "oikoumene", "ekumene",
    "cheiropoeitos", "acheiropoiētos",
    # Greek liturgical and patristic terms
    "epithymia", "epithumia", "epithumiai", "thelema", "thelēma",
    "thelimata", "thelēmata", "boulema", "boulēma", "proairesis",
    "syneidesis", "syneidēsis", "logikos", "alogon", "aphtharsia",
    "phthora", "phtharsia", "athanasia", "athanaton",
    # Personifications, archangels, etc.
    "Michael", "Gabriel", "Raphael", "Uriel", "archangelos", "archistratēgos",
    "thronoi", "kyriotētes", "exousiai", "archai", "dynameis", "cherubim",
    "seraphim", "ophanim", "tetragrammaton",
    # Common Greek vocabulary in transliterated NT studies
    "rabbi", "rabbouni", "didaskale", "didaskalos", "didache",
    "talitha", "koum", "ephphatha", "abba", "elōi", "lema", "sabachthani",
    "hosanna", "ōsanna", "alleluia", "amen", "maranatha",
    # Greek philosophical terms
    "philosophos", "philosophia", "sophos", "sophia", "phronesis",
    "phronēsis", "phronimos", "nous", "noēsis", "noētos", "dianoia",
    "epistēmē", "doxa", "phantasia", "aisthesis", "aisthēsis",
    "logikon", "alogon", "praktikon", "theōrētikon", "poiētikon",
    "hyle", "hylē", "morphē", "morphe", "eidos", "idea", "energeia",
    "dynamis", "entelechia", "telos", "teleios", "teleiōsis",
    # Additional Greek loanwords used in English theological writing
    "Christology", "Christological", "Pneumatology", "Ecclesiology",
    "Eschatology", "Soteriology", "Eucharistic", "Eucharistically",
    "Liturgical", "Liturgically", "Iconography", "Iconographic",
    "Hagiography", "Hagiographic", "Homiletics", "Hermeneutics",
    "Exegesis", "Exegetical", "Patristic", "Patristics", "Patrology",
    "Synodal", "Synodality", "Conciliar", "Conciliarity",
    # Greek words that should not collide with Latin/English
    "exodos", "diaspora", "diasporā", "ethnos", "ethnē", "ethnikos",
    "ethnoi", "presbyterion", "diakonia", "didaskaleia", "paideia",
    "paidagogos", "paidagōgos", "agōgē", "agoge", "askēsis", "askesis",
    "agōn", "agon", "athlon", "athlēsis", "athlēton", "athletes",
    "athleta", "stadion", "dromos", "stephanos", "brabeion",
    # Hebrew-derived Greek
    "satanas", "satan", "diabolos", "demon", "daimōn", "daimon", "Beelzeboul",
    "Beelzebub", "Behemoth", "Leviathan",
    # Greek geography
    "Achaia", "Asia", "Bithynia", "Cappadocia", "Cilicia", "Macedonia",
    "Pamphylia", "Phrygia", "Pontus", "Galatia", "Lykaonia", "Pisidia",
    "Cyprus", "Crete", "Patmos", "Rhodes", "Samos", "Mytilene", "Mitylene",
    "Athens", "Athēnai", "Corinth", "Korinthos", "Thessalonika",
    "Thessalonica", "Berea", "Philippi", "Ephesus", "Ephesos", "Smyrna",
    "Sardis", "Laodicea", "Hierapolis", "Colossae", "Pergamon", "Pergamum",
    "Thyatira", "Antioch", "Damaskos", "Antiocheia",
    # Greek theological in English transliteration
    "kerygmatic", "kerygmatically", "dogmatic", "dogmatics", "dogma",
    "didactic", "homiletic", "homily", "homilies", "anagogical", "anagogy",
    "typological", "typology", "allegorical", "allegory", "tropological",
    "tropology", "mystagogical", "mystagogy",
    # Greek-derived modern Christianese
    "evangelist", "evangelize", "evangelism", "evangelical", "evangelicalism",
    "Pentecost", "Pentecostal", "charismatic", "iconoclast", "iconoclasm",
    "iconographer", "iconography", "theologian", "theological", "theology",
    "soteriology", "Christology", "Mariology", "ecclesiology", "eschatology",
    # Additional Greek tokens
    "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho",
    "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
    # Special Greek Christian words
    "ichthys", "ichthus", "chi-rho", "labarum", "staurogram", "monogram",
    "Theotokos", "theotokos", "Christotokos", "christotokos", "Aeiparthenos",
    "aeiparthenos", "Achrantos", "achrantos", "panagia", "Panagia",
    # Anointing, oils, etc.
    "myron", "myrrh", "chrism", "chrisma", "katechetic", "kyriake",
    "kyriakē", "kuriakon", "synaxis", "synaxarion", "menaion",
    # Liturgical books
    "horologion", "psalter", "psalterion", "psalterium", "evangelistary",
    "lectionary", "menologion",
    # Shared English / Greek theological tokens — kept in both vocabularies
    # so neither gets exclusive credit from them (distinctiveness must come
    # from specialised tokens like pneuma, logos, kurios).
    "spirit", "life",
})
