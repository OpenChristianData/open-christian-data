"""R55 — Layer 2 floor: 60 fixtures across 6 language families must resolve at
layer2 with language_confidence >= 0.60.

RED until classify_block is implemented in build.lib.lang_classifier.
"""

from __future__ import annotations

import pytest

from build.lib.lang_classifier import classify_block


EN_FIXTURES = [
    "Blessed art thou among women",
    "For thine is the kingdom and the power",
    "Verily verily I say unto thee",
    "Hath God forgotten to be gracious",
    "The LORD is my shepherd I shall not want",
    "Thy lovingkindness is better than life",
    "Thus saith the LORD of hosts",
    "Behold the Lamb of God which taketh away the sin",
    "Thou shalt love the LORD thy God with all thine heart",
    "Whereunto I am appointed a preacher and an apostle",
]

LA_FIXTURES = [
    "Pater noster qui es in caelis",
    "Gloria in excelsis Deo et in terra pax",
    "Kyrie eleison Christe eleison",
    "Agnus Dei qui tollis peccata mundi",
    "Sanctus Sanctus Sanctus Dominus Deus Sabaoth",
    "Et incarnatus est de Spiritu Sancto",
    "Credo in unum Deum Patrem omnipotentem",
    "Miserere mei Deus secundum magnam misericordiam tuam",
    "Soli Deo gloria",
    "In principio erat Verbum et Verbum erat apud Deum",
]

FR_FIXTURES = [
    "La grâce de notre Seigneur Jésus Christ",
    "Dieu est amour et celui qui demeure dans l amour",
    "Notre Père qui es aux cieux que ton nom soit sanctifié",
    "Car Dieu a tant aimé le monde qu il a donné son Fils unique",
    "Je suis la résurrection et la vie",
    "La foi sans les oeuvres est morte",
    "L Église de Dieu rachetée par le sang de Christ",
    "Seigneur apprends nous à prier",
    "La parole de Dieu est vivante et efficace",
    "Que votre amour soit sans hypocrisie",
]

DE_FIXTURES = [
    "Die Gnade unseres Herrn Jesus Christus",
    "Gott ist die Liebe und wer in der Liebe bleibt",
    "Gebet und Bibellesen sind die Grundlage des christlichen Lebens",
    "Die Kirche Gottes ist das Fundament der Wahrheit",
    "Der Heilige Geist wird euch in alle Wahrheit leiten",
    "Christus ist das Haupt der Kirche seinen Leibes",
    "Die Reformation hat das Evangelium neu entdeckt",
    "Luther übersetzte die Bibel ins Deutsche",
    "Glaube Hoffnung und Liebe diese drei",
    "Das Wort Gottes bleibt in Ewigkeit",
]

GRC_LATN_FIXTURES = [
    "the logos became flesh and dwelt among us",
    "the agapē of God is shed abroad in our hearts",
    "pneuma is the spirit that gives life",  # Layer 2 lexicon hit — not a source-transliteration term (see test_source_transliteration_lexicon_detects_grc_hbo.py)
    "the ekklesia is the body of Christ",
    "kurios Jesus is Lord over all",
    "the parousia of Christ is the blessed hope",
    "the diatheke is the new covenant in his blood",
    "the christos the anointed one of God",
    "the didache teaches the way of life and death",
    "the kerygma is the proclamation of the gospel",
]

HBO_LATN_FIXTURES = [
    "Yahweh is the covenant name of God in the Hebrew scriptures",
    "Adonai is the name reverently spoken in place of YHWH",
    "Elohim the creator God who made the heavens and the earth",
    "Jehovah Jireh the LORD will provide",
    "Zebaoth the LORD of hosts and of armies",
    "Jahveh a variant transliteration used by German scholars",
    "Jahweh another common German transliteration of the divine name",
    "Yahveh used in some older English-language scholarship",
    "Yehovah a form reflecting the Masoretic vowel pointing",
    "JHVH the tetragrammaton in older European scholarly conventions",
]


@pytest.mark.parametrize("text", EN_FIXTURES)
def test_layer2_english(text: str) -> None:
    result = classify_block(text, "commentary")
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60
    assert result["language"] == "en"


@pytest.mark.parametrize("text", LA_FIXTURES)
def test_layer2_latin(text: str) -> None:
    result = classify_block(text, "commentary")
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60
    assert result["language"] == "la"


@pytest.mark.parametrize("text", FR_FIXTURES)
def test_layer2_french(text: str) -> None:
    result = classify_block(text, "commentary")
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60
    assert result["language"] == "fr"


@pytest.mark.parametrize("text", DE_FIXTURES)
def test_layer2_german(text: str) -> None:
    result = classify_block(text, "commentary")
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60
    assert result["language"] == "de"


@pytest.mark.parametrize("text", GRC_LATN_FIXTURES)
def test_layer2_grc_transliterated(text: str) -> None:
    result = classify_block(text, "commentary")
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60
    assert result["language"] == "grc"


@pytest.mark.parametrize("text", HBO_LATN_FIXTURES)
def test_layer2_hbo_latn(text: str) -> None:
    result = classify_block(text, "commentary")
    assert result["chosen_layer"] == "layer2"
    assert result["language_confidence"] >= 0.60
    assert result["language"] == "hbo_latn"
