"""Hebrew transliteration seed lexicon plus Layer 2 vocabulary."""

from __future__ import annotations


COVERAGE_STATUS = "seed_only"

ARCHAIC_FORMS: dict[str, str] = {
    "Jehovah": "YHWH",
    "Iehovah": "YHWH",
    "JHVH": "YHWH",
    "Jahveh": "YHWH",
    "Jahweh": "YHWH",
    "Yahveh": "YHWH",
    "Yehovah": "YHWH",
    "Jah": "Yah",
    "Eloah": "Eloah (singular form)",
    "Adonai": "Lord",
    "Zebaoth": "Sabaoth",
    "Messias": "Messiah",
}

# Layer 2 vocabulary — transliterated Hebrew theological/biblical terms in Latin script.
# Distinct from native-script Hebrew (Layer 1) — Layer 2 disambiguates Latin-script
# blocks that contain Hebrew loanwords and proper names.
VOCAB: frozenset[str] = frozenset({
    # R55 fixture tokens (divine names and key terms)
    "Yahweh", "Adonai", "Elohim", "Jehovah", "Iehovah", "YHWH", "JHVH",
    "Jahveh", "Jahweh", "Yahveh", "Yehovah", "Zebaoth", "Sabaoth",
    "Jah", "Eloah",
    # Divine names and titles
    "Shaddai", "Shadday", "El-Shaddai", "Elyon", "El", "Eloah", "Elohim",
    "El-Elyon", "Immanuel", "Emmanuel", "Yeshua", "Yahshua", "Yeshu",
    "Messiah", "Mashiach", "Mashiah", "Ruach", "Ruach-HaKodesh", "Kodesh",
    "Hakodesh", "HaShem", "Adonai-Tzva'ot",
    # Holy scriptures, scrolls, books
    "Torah", "Tanakh", "Mishnah", "Midrash", "Talmud", "Halakha", "Halakhah",
    "Haggadah", "Aggadah", "Shema", "Kabbalah", "Zohar", "Pirkei", "Avot",
    "Bereshit", "Shemot", "Vayikra", "Bamidbar", "Devarim",
    "Yehoshua", "Shofetim", "Shoftim", "Shmuel", "Melakhim",
    "Yeshayahu", "Yirmiyahu", "Yechezkel", "Tehillim", "Mishlei",
    "Iyov", "Shir-HaShirim", "Ruth", "Eikhah", "Kohelet", "Esther",
    "Daniel", "Ezra", "Nehemyah", "Divre-HaYamim",
    # Festivals and holidays
    "Shabbat", "Sabbath", "Passover", "Pesach", "Sukkot", "Shavuot",
    "Rosh-Hashanah", "Rosh", "Hashanah", "Yom-Kippur", "Yom", "Kippur",
    "Hanukkah", "Chanukah", "Purim", "Seder", "Haggadah", "Pesachim",
    "Omer", "Lag-BaOmer", "Tisha-BAv", "Tu-BiShvat", "Tu-BAv",
    "Simchat-Torah", "Shemini-Atzeret", "Hoshanah-Rabbah", "Selichot",
    # Religious figures and roles
    "synagogue", "rabbi", "rabban", "Rabbi", "Rabban", "rebbe", "tzaddik",
    "sanhedrin", "Sanhedrin", "levite", "Levite", "kohen", "Kohen", "cohen",
    "Cohen", "priest", "pharisee", "Pharisee", "sadducee", "Sadducee",
    "essene", "Essene", "zealot", "Zealot", "herodian", "Herodian", "scribe",
    "elder", "Nazirite", "Nazir",
    # Place names
    "Judah", "Judea", "Israel", "Galilee", "Jerusalem", "Zion", "Bethlehem",
    "Nazareth", "Jericho", "Jordan", "Sinai", "Hermon", "Tabor", "Carmel",
    "Moriah", "Lebanon", "Damascus", "Nineveh", "Babylon", "Egypt", "Mitzrayim",
    "Canaan", "Kena'an", "Philistia", "Plishtim", "Moab", "Edom", "Ammon",
    "Aram", "Gilead", "Bashan", "Negev", "Negeb", "Shechem", "Shomron",
    "Samaria", "Yehudah", "Yisrael", "Galil", "Yerushalayim", "Tziyon",
    "Bet-Lechem", "Hebron", "Beersheba", "Beer-Sheva", "Megiddo", "Gilgal",
    "Shiloh", "Ramah", "Gibeah", "Mizpah", "Peniel", "Bethel", "Bet-El",
    "Ebenezer", "Ramat", "Tzaphon",
    # Patriarchs, prophets, kings
    "Abraham", "Avraham", "Isaac", "Yitzhak", "Yitzchak", "Jacob", "Yaakov",
    "Esau", "Esav", "Joseph", "Yosef", "Benjamin", "Binyamin", "Levi",
    "Judah", "Yehudah", "Moses", "Moshe", "Aaron", "Aharon", "Miriam",
    "Joshua", "Yehoshua", "Caleb", "Kalev", "Gideon", "Gidon", "Samson",
    "Shimshon", "Samuel", "Shmuel", "Saul", "Shaul", "David", "Dawid",
    "Solomon", "Shlomo", "Elijah", "Eliyahu", "Elisha", "Eliyah",
    "Isaiah", "Yeshayahu", "Jeremiah", "Yirmiyahu", "Ezekiel", "Yechezkel",
    "Daniel", "Hosea", "Hoshea", "Joel", "Amos", "Obadiah", "Ovadyah",
    "Jonah", "Yonah", "Micah", "Michah", "Nahum", "Nachum", "Habakkuk",
    "Chavakuk", "Zephaniah", "Tzephanyah", "Haggai", "Chaggai", "Zechariah",
    "Zekharyah", "Malachi", "Malakhi", "Ezra", "Nehemiah", "Nechemyah",
    "Esther", "Mordecai", "Mordekhai", "Hannah", "Chanah", "Deborah",
    "Devorah", "Jael", "Yael", "Rahab", "Rachav", "Bathsheba", "Bat-Sheva",
    "Abigail", "Avigail", "Sarah", "Sarai", "Rebekah", "Rivkah", "Leah",
    "Rachel", "Rachel", "Zipporah", "Tzipporah", "Hagar", "Dinah",
    # Theological terms
    "hesed", "chesed", "emet", "emunah", "mishpat", "tsedakah", "tzedakah",
    "tsedek", "tzedek", "shalom", "shalom", "teshuvah", "teshuvah",
    "tefillah", "berakhah", "brakhah", "minchah", "korban", "olah", "zebach",
    "todah", "hallel", "hallelujah", "halleluya", "Hallel", "hosanna",
    "amen", "selah", "maranatha", "abba", "imma",
    "kedusha", "kedushah", "kavod", "shechinah", "shekhinah",
    "neshama", "neshamah", "nefesh", "nephesh", "ruach",
    # Worship and prayer
    "siddur", "machzor", "amidah", "Amidah", "kaddish", "Kaddish",
    "shema", "Shema", "barukh", "baruch", "Baruch", "atah", "Atah",
    "atta", "olam", "va-ed", "tzitzit", "tefillin", "phylacteries", "mezuzah",
    "kippah", "yarmulke", "tallit", "tallith", "shofar", "lulav", "etrog",
    "menorah", "hanukkiah", "chanukkiah",
    # More biblical figures and tribes
    "Reuben", "Reuven", "Simeon", "Shimon", "Naphtali", "Naftali",
    "Dan", "Gad", "Asher", "Issachar", "Yissachar", "Zebulun", "Zevulun",
    "Manasseh", "Menasheh", "Ephraim", "Efrayim",
    "Adam", "Chavah", "Eve", "Cain", "Kayin", "Abel", "Hevel", "Seth",
    "Shet", "Enosh", "Enoch", "Hanoch", "Methuselah", "Metushelach", "Noah",
    "Noach", "Shem", "Ham", "Cham", "Japheth", "Yefet", "Nimrod",
    "Terah", "Terach", "Nahor", "Nachor", "Lot", "Ishmael", "Yishmael",
    "Keturah",
    # Kings and queens
    "Rehoboam", "Rechavam", "Jeroboam", "Yerovam", "Hezekiah", "Chizkiyahu",
    "Josiah", "Yoshiyahu", "Manasseh", "Menasheh", "Ahaz", "Achaz",
    "Amaziah", "Amatzyahu", "Uzziah", "Uziyahu", "Jotham", "Yotam",
    "Athaliah", "Atalyah", "Ahab", "Achav", "Jezebel", "Izevel",
    "Omri", "Jehu", "Yehu", "Joash", "Yoash",
    # Tabernacle, temple, priestly
    "mishkan", "Mishkan", "Tabernacle", "tabernacle", "Beit-HaMikdash",
    "Bet-HaMikdash", "Aron", "Aron-HaBrit", "Ark", "menorah", "shulchan",
    "showbread", "lechem", "panim", "ketoret", "incense", "olah",
    "burnt-offering", "mincha", "minchah", "grain-offering", "chatat",
    "sin-offering", "asham", "trespass-offering", "shelamim", "shelmim",
    "peace-offering", "moadim", "yamim-tovim", "rosh-chodesh", "Rosh-Chodesh",
    "calendar", "Hebrew-calendar",
    # Months
    "Nisan", "Iyar", "Sivan", "Tammuz", "Av", "Elul", "Tishrei", "Tishri",
    "Cheshvan", "Marcheshvan", "Kislev", "Tevet", "Shevat", "Adar",
    # Cardinal Hebrew words
    "ben", "bat", "Ben", "Bat", "bnei", "bnot", "av", "em", "Av", "Em",
    "shalom", "todah", "anachnu", "anokhi", "ata", "atem", "hu", "hi",
    "hem", "hen", "asher", "ki", "lo", "ken", "od", "ach", "rak",
    "im", "lulei", "lamah",
    # Other Hebrew vocabulary
    "Tishbite", "tetragrammaton", "Tetragrammaton", "Nicolaitan",
    "Pentateuch", "Hexateuch", "Heptateuch", "Octateuch", "Megilloth",
    "Megillah", "ketuvim", "Ketuvim", "nevi'im", "Nevi'im", "Tehilim",
    # Hebrew NT and intertestamental figures
    "Yochanan", "Yochanan-HaMatbil", "Yohanan", "Maryam", "Miryam",
    "Yosef", "Yehudah", "Yaakov", "Kefa", "Shaul", "Bar-Yochanan",
    "Bar-Mitzvah", "Bat-Mitzvah",
    # Land and topography
    "Eretz", "Eretz-Yisrael", "ha-aretz", "Mizrayim", "Yam-Suf",
    "Yam-HaMelach", "Kinneret", "Yarden",
    # Liturgical items
    "Mizbeach", "altar", "Bamah", "Asherah", "Massebah",
    # Christian Hebrew transliteration
    "Yeshua", "HaMashiach", "Hashiach", "Yeshua-HaMashiach",
    "Notzri", "HaNotzri", "Yeshu", "Ben-Adam",
    # Hebrew biblical and Talmudic vocabulary
    "covenant", "berit", "brit", "circumcision", "milah", "bar-mitzvah",
    "bat-mitzvah", "Shavuot", "matan-Torah", "kabbalah", "Cabala",
    "Zohar", "Sefirot", "Sephirot", "Ein-Sof", "Adam-Kadmon",
    "tikun", "tikkun", "tikkun-olam", "olam-haba", "olam-hazeh",
    "gehinnom", "gehenna", "sheol", "Sheol", "Hades",
    # Additional Hebrew place names
    "Bet-El", "Bethel", "Bet-Lechem", "Bethlehem", "Bet-Shean", "Beth-Shean",
    "Bet-Shemesh", "Beth-Shemesh", "Hebron", "Chevron", "Hevron",
    "Beersheba", "Beersheva", "Jericho", "Yericho", "Yereho", "Aijalon",
    "Ayalon", "Gibeon", "Givon", "Anathoth", "Anatot",
    # Hebrew religious terms
    "yeshiva", "Yeshiva", "kollel", "Kollel", "minyan", "Minyan",
    "chevruta", "Chevruta", "Bavli", "Yerushalmi", "gemara", "Gemara",
    "Mishnah", "Tosefta", "Baraita", "rishonim", "Rishonim", "acharonim",
    "Acharonim", "tanna", "Tanna", "amora", "Amora", "tannaim", "amoraim",
    # Hebrew names of God variants
    "Tetragrammaton", "tetragram", "Tetragram", "Tetragrammon",
    "Yah", "JAH", "Shaddai", "El-Shaddai", "Elohenu", "Eloheinu",
    "Avinu", "Avinu-Malkenu", "Malkenu", "Boreh", "Bore", "Yotzer",
    # Hebrew sin-and-redemption vocabulary
    "chet", "chait", "avon", "pesha", "kapparah", "geulah", "ge'ulah",
    "yeshu'ah", "yeshua", "moshia", "moshi'a", "po'el", "fele",
    "nes", "nissim", "ot", "ototh", "mofet", "mofetim",
    # Hebrew priesthood
    "Aaronic", "Levitical", "Zadokite", "Tzadokite",
    # More NT Hebrew background
    "Mishna", "Mishnah", "Talmudic", "Talmudical", "Halakhic", "Halakhically",
    "Aggadic", "Midrashic", "Mishnaic", "Tannaitic", "Amoraic",
    "Rabbinic", "Rabbinical", "Rabbinically",
    # Hebrew expressions
    "barukh-ata", "baruch-atah", "barukh-shem", "baruch-shem", "Hodu",
    "L'Adonai", "ki-tov", "ki-leolam", "chasdo", "chesed-olam",
    # Hebrew personal names extras
    "Lemech", "Tubal-Cain", "Naamah", "Shem", "Cham", "Yefet",
    "Avram", "Sarai", "Hagar", "Yishmael", "Yitzchak", "Esav", "Yaakov",
    "Leah", "Rachel", "Bilhah", "Zilpah",
    # Additional Hebrew-Aramaic-Christian
    "Aramaic", "Targum", "Targumim", "Peshitta", "Peshito", "Edessa",
    # General Hebrew-influenced English Christian terms
    "Hosanna", "Selah", "Maranatha", "Abba", "Amen", "Hallelujah",
    "Hallelujahs", "Eden", "Adamic", "Noahide", "Abrahamic", "Mosaic",
    "Davidic", "Solomonic", "Aaronic", "Levitical", "Messianic",
    # Hebrew greetings and life-cycle
    "Mazel-tov", "Shalom-aleichem", "Aleichem-shalom", "Shavua-tov",
    "Shabbat-shalom", "Bruchim", "Baruch-haba", "L'chaim",
})
