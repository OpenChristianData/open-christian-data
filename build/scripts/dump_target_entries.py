"""Dump target entries from registry for review."""
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = str(REPO_ROOT / "data" / "authors" / "registry.json")

TARGET_IDS = [
    'abba-poemen', 'abercius', 'abraham-of-nathpar', 'acacius-of-beroea', 'acacius-of-caesarea',
    'adamantius', 'adamnan', 'adamnan-of-iona', 'agapius-of-hierapolis', 'alcuin-of-york',
    'alexander-of-alexandria', 'alexander-of-jerusalem', 'ambrose-of-milan', 'ambrosian-hymn-writer',
    'ambrosiaster', 'ammon-of-hadrianopolis', 'ammonas-of-egypt', 'ammonius-of-alexandria',
    'amphilochius-of-iconium', 'ancient-greek-expositor', 'andreas-of-caesarea', 'andrew-of-crete',
    'anselm-of-canterbury', 'anselm-of-laon', 'anthony-the-great', 'aphrahat-the-persian-sage',
    'apollinaris-of-laodicea', 'aponius', 'apringius-of-beja', 'arator', 'archelaus-of-carrhae',
    'arethas-of-caesarea', 'arius', 'arnobius-of-sicca', 'arnobius-the-younger',
    'asterius-of-cappadocia', 'athanasius-of-alexandria', 'athenagoras-of-athens',
    'augustine-of-hippo', 'aurelius-prudentius-clemens', 'basil-of-caesarea', 'basil-of-seleucia',
    'bede', 'benedict-of-nursia', 'berengaudus', 'bernard-of-clairvaux', 'besa-the-copt',
    'braulio-of-zaragoza', 'cs-lewis', 'caius-presbyter-of-rome', 'callistus-i-of-rome',
    'cassiodorus', 'chromatius-of-aquileia', 'clement-of-alexandria', 'clement-of-rome',
    'commodian', 'cosmas-of-maiuma', 'cyprian', 'cyril-of-alexandria', 'cyril-of-jerusalem',
    'desert-fathers', 'dhuoda-of-septimania', 'diadochos-of-photiki', 'didymus-the-blind',
    'diodorus-of-tarsus', 'dionysius-of-alexandria', 'dionysius-of-corinth', 'dorotheos-of-gaza',
    'douglas-wilson', 'ephrem-the-syrian', 'epiphanius-scholasticus', 'epiphanius-of-salamis',
    'erasmus-of-rotterdam', 'eucherius-of-lyon', 'eugippius', 'eusebius-of-caesarea',
    'eusebius-of-emesa', 'eusebius-of-gaul', 'eusebius-of-vercelli', 'eustathius-of-antioch',
    'evagrius-ponticus', 'eznik-of-kolb', 'fabian-of-rome', 'facundus-of-hermiane', 'fastidius',
    'faustinus-of-lyon', 'faustus-of-riez', 'fructuosus-of-braga', 'fulgentius-of-ruspe',
    'gk-chesterton', 'gaius-marius-victorinus', 'gaudentius-of-brescia', 'gaudentius-of-rimini',
    'gennadius-of-constantinople', 'gennadius-of-massilia', 'gregory-palamas', 'gregory-of-elvira',
    'gregory-of-nazianzus', 'gregory-of-nyssa', 'gregory-the-dialogist', 'haimo-of-auxerre',
    'haymo-of-halberstadt', 'hegemonius', 'hegesippus', 'heracleon', 'hesychius-of-jerusalem',
    'hilary-of-arles', 'hilary-of-poitiers', 'hippolytus-of-rome', 'horsiesios', 'hugh-of-saint-cher',
    'ildefonsus-of-toledo', 'isaac-of-nineveh', 'isaiah-the-solitary', 'ishodad-of-merv',
    'isidore-of-pelusium', 'isidore-of-seville', 'jb-lightfoot', 'jrr-tolkien', 'jacob-bar-salibi',
    'jacob-of-edessa', 'jacob-of-serugh', 'jerome', 'john-cassian', 'john-damascene',
    'john-i-of-antioch', 'john-wesley', 'john-of-cressy', 'john-of-dalyatha', 'john-of-karpathos',
    'john-of-the-cross', 'john-the-solitary', 'josephus', 'julian-of-eclanum', 'julian-of-toledo',
    'julianus-pomerius', 'julius-africanus', 'julius-firmicus-maternus', 'justin-martyr',
    'lanfranc-of-canterbury', 'leander-of-seville', 'leo-the-great', 'lucifer-of-cagliari',
    'lucius-caecilius-firmianus-lactantius', 'macarius-of-egypt', 'macrina-the-younger',
    'magnus-felix-ennodius', 'malchion', 'marcus-eremita', 'marcus-minucius-felix',
    'martin-luther', 'martin-of-braga', 'maximus-of-turin', 'maximus-the-confessor',
    'melito-of-sardis', 'methodius-of-olympus', 'nemesius-of-emesa', 'nerses-of-lambron',
    'nicetas-of-remesiana', 'nicholas-of-gorran', 'nicholas-of-lyra', 'nilus-of-sinai',
    'novatian', 'oecumenius', 'olympiodorus-of-alexandria', 'optatus-of-milevis',
    'oresiesis-heru-sa-ast', 'origen-of-alexandria', 'pachomius-the-great', 'pacian-of-barcelona',
    'palladius-of-antioch', 'palladius-of-galatia', 'pamphilus-of-caesarea', 'papias-of-hierapolis',
    'papias-the-lexicographer', 'paschasius-radbertus', 'paschasius-of-dumium', 'paterius',
    'patrick-of-ireland', 'paulinus-of-milan', 'paulinus-of-nola', 'paulus-orosius', 'pelagius',
    'peter-chrysologus', 'peter-olivi', 'peter-of-alexandria', 'petrus-alphonsi',
    'philastrius-of-brescia', 'phileas-of-thmuis', 'philo-of-alexandria', 'philoxenus-of-mabbug',
    'photios-i-of-constantinople', 'polycarp-of-smyrna', 'polycrates-of-ephesus', 'pope-anterus',
    'pope-dionysius', 'pope-pontian', 'pope-urban-i', 'pope-zephyrinus', 'possidius',
    'potamius-of-lisbon', 'primasius-of-hadrumetum', 'proclus-of-constantinople',
    'procopius-of-gaza', 'prosper-of-aquitaine', 'prudentius', 'quodvultdeus', 'rabanus-maurus',
    'remigius-of-rheims', 'richard-of-saint-victor', 'robert-of-tombelaine', 'romanos-the-melodist',
    'sahdona-the-syrian', 'salvian-the-presbyter', 'severian-of-gabala', 'severus-of-antioch',
    'shenoute-the-archimandrite', 'socrates-scholasticus', 'sophronius-of-jerusalem',
    'sulpicius-severus', 'symeon-the-new-theologian', 'syncletica-of-alexandria',
    'tatian-the-assyrian', 'theodore-stratelates', 'theodore-of-mopsuestia', 'theodoret-of-cyrus',
    'theodorus-of-tabennese', 'theodotus-of-ancyra', 'theognostus-of-alexandria',
    'theonas-of-alexandria', 'theophanes-of-nicaea', 'theophilus-of-alexandria',
    'theophilus-of-antioch', 'theophylact-of-ohrid', 'thietland-of-einsiedeln', 'thomas-aquinas',
    'ticonius', 'titus-of-bostra', 'tyrannius-rufinus', 'valentinus', 'valerian-of-cimiez',
    'venerable-barsanuphius-and-john-the-prophet', 'verecundus-of-junca', 'victor-vitensis',
    'victor-of-cartenna', 'victorinus-of-pettau', 'vigilius-of-thapsus', 'vincent-of-lerins',
    'walafrid-strabo', 'zephyrinus'
]

with open(REGISTRY_PATH, encoding='utf-8') as f:
    data = json.load(f)

target_set = set(TARGET_IDS)
found = []
not_found = []

for author in data['authors']:
    if author['author_id'] in target_set:
        found.append(author['author_id'])
        print(json.dumps(author))

missing = target_set - set(found)
import sys
print(f"\n--- SUMMARY ---", file=sys.stderr)
print(f"Found: {len(found)}, Missing from registry: {len(missing)}", file=sys.stderr)
if missing:
    print(f"Missing: {sorted(missing)}", file=sys.stderr)
