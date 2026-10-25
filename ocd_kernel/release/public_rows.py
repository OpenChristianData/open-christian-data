"""Bound, reversible omissions at the offline public-row boundary."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import quote, unquote

from ocd_kernel.library._common import PipelineError, canonical_bytes, safe_identifier

from .public_allowlist import _LOCAL_PATH, _scan
from . import final_public_privacy, public_rights
from . import publick_worship, form_church_government, solemn_league, sum_saving_knowledge, bcp1662_public, spurgeon_mtp_public, bcp1549_public, aquinas_public, watson_body_public, bcp1559_public, catholic_encyclopedia_public


CONTRACT = "ocd-public-source-location-omissions-v1"
FIELD = "provenance.source_location"
HISTORICAL_CONTRACT = "ocd-public-historical-format-omissions-v1"
EDWARDS_SELECT_CONTRACT = "ocd-public-edwards-select-sermons-outline-and-format-v1"
EDWARDS_SELECT_ITEM = "edwards-select-sermons--edwards-select-sermons-ccel-thml-electronic"
EDWARDS_SELECT_LICENSE = "Public domain (United States) for Jonathan Edwards's historical sermon text; CCEL electronic collection and factual indexes used under private educational text-use terms"
EDWARDS_SELECT_SCOPE_SHA256 = "eb450663f2f06cca72fe288f54c5e7dd228d79417c182b86d5d31406b230cbf0"
EDWARDS_SELECT_PRIVATE_ROWS_SHA256 = "f5f047f43315c441343e74e615efa33051176a5c9c17596467b9725e3335402b"
EDWARDS_SELECT_NOTICE_NODE_SHA256 = "47a786c9b5a03b72d75a084b022ec4852599ae27b984ac5ac0d1792f4c1edfc9"
EDWARDS_SELECT_OUTLINE_NODE_SHA256 = "027dc8a58d917345d8bdc0002b58a8860842e3364cae0282e8bc9d78c3c6ef67"
GREEN_CONTRACT = "ocd-public-green1888-source-role-rewrite-v1"
GREEN_ITEM = "elisha-w-green-life-1888--green-docsouth-electronic"
BENNETT_ITEM = "expositors-bible--w-h-bennett--expositors-bible--w-h-bennett--bennett-expositor10--ccel-electronic"
BENNETT_SCOPE_SHA256 = "f7fc7117acf2a1f9c1fa1c2b6e0229bcbf0231d6860ac49318878a2221f794f3"
GREEN_ACCEPTANCE_SHA256 = "de2bb963267b04fb833f627d1f41dcf6b02cdc3a40ee75f39554e80c49ab9d28"
GREEN_MASTER_SHA256 = "011dc75db7ca61688bafa0e84f376e93c88ad5071f9244ce003d4e33b730563d"
GREEN_PRIVATE_ROWS_SHA256 = "0c12b94e21ff284fd29ff32254576de801bebfe78b0eda303f7cc3e0ea7bf7ca"
GREEN_PREFIX = "urn:ocd:green1888:source-role:"
PG_CONTRACT = "ocd-public-pg-source-bookkeeping-v1"
SPURGEON_CONTRACT = "ocd-public-spurgeon-morneve-source-layer-v1"
EDWARDS_CONTRACT = "ocd-public-edwards-affections-source-layer-v1"
EDWARDS_ITEM = "edwards-religious-affections--ccel-thml-electronic-witness"
EDWARDS_LICENSE = "Public domain (United States) for Jonathan Edwards's historical text; CCEL-sourced factual scripture-reference index"
EDWARDS_ACK_SOURCE_ROW_SHA256 = "1f9b980ff6ebabb068e302e4e0064871beff3c46938fe474d1bb5b8b268f9d89"
EDWARDS_ACK_ROW_SHA256 = "b28ad2ab7a11f8a55b72a4f816cf03002119ab09c737fcb3a1866a9df8aee8f5"
BOUNDS_CONTRACT = "ocd-public-bounds-power-historical-text-v1"
BOUNDS_ITEM = "bounds-power-through-prayer--bounds-power-through-prayer-ccel-thml-electronic"
BOUNDS_LICENSE = "Public domain (United States) for identified historical text; CCEL electronic source used with retained text-use permission for private offline preparation"
BOUNDS_ACCEPTANCE_SHA256 = "3e882bb5beccab01973daef0e660d6e18faa6b77d2996659748e91b52d1e676c"
BOUNDS_MASTER_SHA256 = "9e3b3b2da1e5fc8d5b3729bb7534795b13fa1e138410646c65d927de76aa87bc"
BOUNDS_PRIVATE_ROW_SHA256 = "274fd5afff2b797dec05374edc02a069f79dab88e3d92285753dbbf24ffc9b73"
BOUNDS_PUBLIC_ROW_SHA256 = "47dabf89af811b5093a86fe3ebe2ed39401af6b0bf8a4091526793c19f4307b3"
BOUNDS_PROMOTIONAL_PARAGRAPHS = {
    12: "92f7831d50952f76c6f0b5abde6f4039e6e27155bde843a8037ca5f73a95b132",
    14: "b07966e1a2a3a9a9f0b18c685b7addd8cd0f9052e7b2d9f9ca15bcf3d1511494",
}
BUNYAN_CONTRACT = "ocd-public-bunyan-grace-historical-text-v1"
BUNYAN_ITEM = "bunyan-grace-abounding--bunyan-grace-abounding-ccel-thml-electronic"
BUNYAN_LICENSE = "Public domain (United States) for identified 1666 Bunyan historical text and factual scripture index; CCEL electronic source used with retained text-use permission for private offline preparation"
BUNYAN_ACCEPTANCE_SHA256 = "202965204aa31132d3443577e794d97ebf76aa0064dfd385867057654342eea8"
BUNYAN_MASTER_SHA256 = "8da7b1534bd8ef88fe6c2e15dc5496e9d0f0d4d1906265fc311418b44eb0e607"
BUNYAN_PRIVATE_ROW_SHA256 = "ba902ffb87b6e1952dd5f9f66a44a53e521815bf850c23540d163f68822d973a"
BUNYAN_PUBLIC_ROW_SHA256 = "b553e7b3b877ac705f7fa72f1c9a65a54e8d8cf2b2863e34a46a5d0f98110d5f"
BUNYAN_FOREWORD_SHA256 = "3ae81557ada73ec0c9b9c532382183405a66634740efc59f6513429fbb79792d"
BUNYAN_SEPARATOR_SHA256 = "e2bed6edf5700c3421c43448e6c969a013d37928a8b544f6120b98582289f44e"
SPURGEON_ITEM = "spurgeons-morning-evening--spurgeons-morning-evening-ccel-thml-electronic"
SPURGEON_LICENSE = "Public domain (United States) for identified historical devotional text only; CCEL educational and noncommercial electronic-source terms apply to private offline preparation"
SPURGEON_PRIVATE_ROW_SHA256 = "f1ce723ec8b003e12e221c311a034e440d4a325b0af4b60792c5a6bfff82bed6"
SPURGEON_PARAGRAPH_SHA256 = "d91d5d087e1970f26a6e672bac7eaa1ada45070ccc3164ace84b59f07f34f597"
SPURGEON_SCOPE_SHA256 = "3b17ad969deb309cddef2f99decd683b35d5f67f73aa965e94ec930e15dfeefb"
SPURGEON_MARKER = "urn:ocd:lib030:source-unit:DayOfYear"
SPURGEON_PUBLIC_MARKER = "source-unit:DayOfYear"
FINNEY_CONTRACT = "ocd-public-finney-1878-modern-publisher-omissions-v1"
FINNEY_ITEM = "finney-systematic-theology--finney-systematic-theology-ccel-thml-electronic"
FINNEY_LICENSE = "Public domain (United States); identified historical text and apparatus only"
FINNEY_ACCEPTANCE_SHA256 = "055051c61c54302f33db5042ddf57ad5267f17fa771ccf5d6697bf20b7074fa4"
FINNEY_MASTER_SHA256 = "0279e624d8e3c63005e94b8baae9b2fbae5efb57e8fbc759ff34bff19290386b"
FINNEY_PRIVATE_ROW_SHA256 = "168120b40c170e66b11444f88d87ece9552b88cdc78dccf01ea9ba208b171fd6"
FINNEY_PUBLIC_ROW_SHA256 = "d3f59433f8db7de1d947f1c96a2afc4023426b45660bc5112f439afe80702a84"
FINNEY_FRONT_TAIL_SHA256 = "c300cc02e05743f3bc18a1f903b29087a971a86aea91f4b050f1c95b5e3a51c5"
FINNEY_MAIN_TAIL_SHA256 = "99126d5cfcedb5866661ddc7a722d76bc814b18e60c305a5dfd4cfc786118e0e"
FINNEY_SCOPE_SHA256 = "f8105d43c88127538dba6b93313b0384f02484528cffa8536507548cd90eb7a6"
CHARNOCK_CONTRACT = "ocd-public-charnock-v1-ledger-and-publisher-omissions-v1"
CHARNOCK_ITEM = "charnock-existence-attributes-vol-1--charnock-existence-attributes-vol-1-retained-electronic-witness"
CHARNOCK_LICENSE = "Public domain (United States) for 1853 Charnock/Symington text and historical apparatus; factual Baker reprint imprint and Project Gutenberg electronic transcription notes with source credit"
CHARNOCK_ACCEPTANCE_SHA256 = "fc15ffa0ccaf84094fb6c6af0718060a5c058d5d266aedd1e93a72b4a12c6b4a"
CHARNOCK_MASTER_SHA256 = "3b39bcf64176f0862b8b7686c6fc9e23951b584b4f5d86c0ce190802ff2cf289"
CHARNOCK_SCOPE_SHA256 = "58ddab262abfb6fd01eb68d0f7992b98cb4e573495fdc7464bc22bcb6171b19d"
CHARNOCK_PRIVATE_ROWS_SHA256 = "a3dd46aed5581acb93b24e3d855ff8f1d1750ba972c8730cddf5ff9af928359c"
CHARNOCK_PUBLIC_ROWS_SHA256 = "422adb7f56d382f8ebf2e1fd825abd4d8e6e743e98feaecd1d2589d0da7c1027"
CHARNOCK_VOLUME_LEDGER_SHA256 = "910ec01051844cbfb8a4581d0aadb6281707c04a2c208e11447fb1815f67a353"
CHARNOCK_SHARED_LEDGER_SHA256 = "39159fe6431bc44735792508813ade8773079bd43cf7066a4fdd38ea628a299c"
CHARNOCK_PROMOTION_SHA256 = "8067e4192123125f2fe458c7588e82127478feeece05209175c3fc143b989ab7"
CHARNOCK_V2_CONTRACT = "ocd-public-charnock-v2-ledger-omissions-v1"
CHARNOCK_V2_ITEM = "charnock-existence-attributes-vol-2--charnock-existence-attributes-vol-2-retained-electronic-witness"
CHARNOCK_V2_LICENSE = "Public domain (United States) for 1853 Charnock Volume II text and historical apparatus; Project Gutenberg electronic transcription notes with source credit"
CHARNOCK_V2_ACCEPTANCE_SHA256 = "fdb415c4bc629923e94fe85392955430592f30801b3f3c47573dd0cf4337970d"
CHARNOCK_V2_MASTER_SHA256 = "d0ded49a98ab3e6eb00c589f7272c872c19c9ffc5b839cd01c41164120ec0ba8"
CHARNOCK_V2_SCOPE_SHA256 = "e7e87f6d89df0526050f9037d9aaa319572bfbfcb119d5b42d4bd3433c3ee6f6"
CHARNOCK_V2_PRIVATE_ROWS_SHA256 = "2dc571e09b7ca8f2157c1f0790257f69c217048238c06e381d0db2a27cccd416"
CHARNOCK_V2_PUBLIC_ROWS_SHA256 = "c3af3bfae0d4c236e0d007fd51e499b709745158aa0a14c96d7199d017fe2f8a"
CHARNOCK_V2_VOLUME_LEDGER_SHA256 = "e12474456490bd22dd5cf92044e5f4b40a1eab51f317a239a44f907395be5d5d"
CHARNOCK_V2_SHARED_LEDGER_SHA256 = "34c84d12214fb6ddc187164f66a2fb9104236cf7c8ccae3fce517e12d90c619e"
NOAH_ITEM = "noah-davis-narrative-life-1859--noah-davis-narrative-life-1859-pg20005"
# Exact accepted authorities from PG52 and separately reviewed Campion.
# These are source-bound public repairs, not new rights or acceptance decisions.
NEWMAN_ITEM = "newman-development-christian-doctrine--newman-development-christian-doctrine-gutenberg-electronic"
NEWMAN_GREEK_MARKER = "urn:ocd:greek-transliteration"
NEWMAN_PUBLIC_MARKER = "source-annotation:greek-transliteration"
PG_ITEMS = {
    NEWMAN_ITEM: ("3d4e48d90c1d03d1d64520c30515fa42c4fcd811ff9160d764c3259696837612", "03bf082f6f366163bdf14ea917108cbe393c5257313d739b2585cf0178d2938a"),
    SPURGEON_ITEM: ("38052dc4bf2dfd7b0b1ccab73e4c24123a5823b661742eee8f4edbd20b062053", "9abbca4ffd8498fdc6f7867772a8caf32cb19cbaa0c5e96580f5ea58b9365023"),
    "teresa-life-of-st-teresa-of-jesus--teresa-life-of-st-teresa-of-jesus-gutenberg-electronic": ("c22c1308330c780146f8ae6e99fd7776da9cb62a734ef9e709598390e2c6bc01", "7cfdcd709d87f8cf52ae626e360285e30f0d79d9cff679348587051ac1f2d8ea"),
    "noah-davis-narrative-life-1859--noah-davis-narrative-life-1859-pg20005": ("4182fcfe5d35afa6524f181219d48434df0e28f52b2fcb3417559454dd20ef4e", "d732a99bb7cbc42742378de115317732ac3859d95a174c2ddda25b897cbe3c74"),
    "modern-scepticism-christian-evidence-society-1871--modern-scepticism-christian-evidence-society-1871-gutenberg-electronic": ("231677839f83d469a0515b8b610f4d4c9b2ddc7fa1084f68796df1a82ee97e32", "fb8d4b5c24eef296b3e0f33468056172751a7e47a2678e8dacc444bf903c6107"),
    "louise-imogen-guiney-blessed-edmund-campion--pg52731-1914": ("1eb43ad355ddefb1c55da6a87a7a404fd20a765b7ee7edd70a83ea567c92216e", "ff6bc90d654f350003a7b49989c5ed2cc4a4ee461d91e282b326a1f5ff395dad"),
    "edward-judson-life-of-adoniram-judson--judson-life-of-adoniram-judson-1883-pg70894": ("5331508ec87317aa97ea2ded546ec0e42a5fa1c4991b5f6733e3fd6809ec9d58", "452ea076c443ae581bd8a6c34c632fa9bf676043a987a13e94dc31eef4cc8e65"),
    "gerhardt-spiritual-songs--gerhardt-spiritual-songs-gutenberg-electronic": ("408ec41f80aa307688f874a0d06259051a7d6e9401b7afffff7df265607bbae1", "c347072830f0e12e68e02f56e97b633beaecb46a3b8f9d95abf70c52939680f2"),
    "jarena-lee-religious-experience-and-journal--jarena-lee-religious-experience-and-journal-gutenberg-electronic": ("3e58fc78cf0abeb417f87349f007adafc4523986b0032057d67e1562b2d0173f", "87f30783b5d46fb9547d0d4bb0e3831de869779b3364aa632b4308765b637ca6"),
    "keble-christian-year--keble-christian-year-gutenberg-electronic": ("21a75ddcf2b3f72931f6f2d8d8cc538b3aa1f44fe4ae000634769ef32bad9de9", "602aaafc65296d4516b286622a7dc6b007b1db43d57acb8987b8444d564423a9"),
    "paton-missionary-new-hebrides-autobiography-3vol-aggregate--paton-autobiography-three-volume-pg-edition": ("582bc25a6ddaa307aad16687f715e826ab3415599cf35c1737c909dac0bf4162", "f4bfcc46e37b9535e7cb7b15f453ed98b0e6980173d71879c750b3eb1552f5ef"),
    "pg49917-assumption-sermon-i--pg49917-assumption-sermon-i-pg49917-edition": ("314e485edc0267fec02773dc41b7f09f1d8e2fbd4b7059747d8d92005b1d7b11", "d888df20a5eaf43429bd0f52c3369b6f1abc79936007d4921cf94e91a99c426b"),
    "pg49917-assumption-sermon-ii--pg49917-assumption-sermon-ii-pg49917-edition": ("9cd75446960d057481cf1fcff88207f7efb94d347910eb6678f0f7fb85667b95", "acd499fc37a113405c22136086c466d81f33a05944955b2378be4c7904221062"),
    "pg71937-exhortation--pg71937-exhortation-pg71937-edition": ("fae3d356e74db401018ad46b3cc188677ac299c0ebec69315be0780d3ab69605", "f636e7cf63378a0f707fd8cc81377a2fc9f54458066c2b2151db361d31a3f6f0"),
    "pg71937-instructor--pg71937-instructor-pg71937-edition": ("6a4bf725ac67ed2c4c85e2d16015aa9ac8bdb134cb7d3ca9fc02abecb0009f51", "1f39311b943ee6a8b9def9bd6dc942c1b4b87a1e24fd1e2640f78ff8d6978820"),
    "pg71937-stromata--pg71937-stromata-pg71937-edition": ("00aa4f0443066caa529c12125881b779cca21af3249f15c445cbcc20cd4bb1f3", "23f77904bcef3725dc42313f71c91e27bdd7d1d1d393d332c0603d74a710b644"),
    "pg71937-stromata--pg71937-stromata-pg73020-edition": ("3015a1488b052b891447d7ea7a4eb94368073b9f24be2e89f7f497cb001c4a33", "efec815721d3b449e342b48c7fdf6689a6b4778739e28d63970a39db04c1506e"),
    "tyerman-oxford-methodists-1873--pg70497-1873-harper-brothers": ("1b4d92091b4dbb9d44cb8e7f3547f44a8376c3ed67f2768e7ace9fa0fb573b9e", "59d558ab184ce0cb153e0012c90aee7e59119576f27ebcbda3c8d1baaace488c"),
    "william-derham-physico-theology-1720--pg75254-1720-london": ("8318a3d5129979ae40e5ba36ac232063b7d1e95098859d05c43ae3bc608c379d", "00042d7571bd0b8ff41c2285ce9d23c6f4e20429e9dd0a8ef42da01f91762cb1"),
}
PG_BOOK_ITEMS = frozenset({
    "noah-davis-narrative-life-1859--noah-davis-narrative-life-1859-pg20005",
    "louise-imogen-guiney-blessed-edmund-campion--pg52731-1914",
    "edward-judson-life-of-adoniram-judson--judson-life-of-adoniram-judson-1883-pg70894",
    "tyerman-oxford-methodists-1873--pg70497-1873-harper-brothers",
    "william-derham-physico-theology-1720--pg75254-1720-london",
})
PG_ORDINAL_ITEMS = frozenset({
    "gerhardt-spiritual-songs--gerhardt-spiritual-songs-gutenberg-electronic",
    "keble-christian-year--keble-christian-year-gutenberg-electronic",
})
PG49917_ITEMS = frozenset(item for item in PG_ITEMS if item.startswith("pg49917-assumption-sermon-"))
CLEMENT_ITEMS = frozenset(item for item in PG_ITEMS if item.startswith("pg71937-"))
PG42957_ITEM = "modern-scepticism-christian-evidence-society-1871--modern-scepticism-christian-evidence-society-1871-gutenberg-electronic"
PG42957_ROW_REND = "urn:ocd:pg42957:legacy-row-rend:smaller"
TERESA_ITEM = "teresa-life-of-st-teresa-of-jesus--teresa-life-of-st-teresa-of-jesus-gutenberg-electronic"
TERESA_PRIVATE_ANNOTATION = "urn:ocd:abbreviation-expansion"
TERESA_PUBLIC_ANNOTATION = "abbreviation-expansion"
GREEN_ROLES = {
    "titlePage": ("source-title-page", []),
    "docTitle": ("source-block", []),
    "titlePart": ("source-block", [["type", "main"]]),
    "docImprint": ("source-block", []),
    "pubPlace": ("source-block", []),
    "publisher": ("source-block", []),
    "docDate": ("source-block", []),
    "corr": ("source-editorial-correction", [["rend", "[space]"]]),
}
# The exact item, acceptance, and master bindings come from the reviewed
# CCEL second-cohort disposition, SHA-256 46eeb109c0d6f928d8f1a21bc84f7770392b515bc258c07df18cf4938b1fc3b4.
HISTORICAL_RIGHTS_SHA256 = "46eeb109c0d6f928d8f1a21bc84f7770392b515bc258c07df18cf4938b1fc3b4"
# Field inventory only; the separate rights and notices remain release selection duties.
HISTORICAL_FORMATTING_SCOPE_SHA256 = "0cd3f0c8534f9bed9f977dd0effe176aeec093e5f31e74b6889a213003b2f55c"
RYLE_ITEM = "ryle-holiness--ryle-holiness-retained-electronic-witness"
RYLE_SCOPE_SHA256 = "2785a4d6fb3ecdd8c467a95564b19e3f45dabfa19cabda5b8f9479f15ac37c9a"
RYLE_PRIVATE_ROWS_SHA256 = "f813d2d5992375f07ba910cb2851a94ed5153b57bf937204b7ec9155fa6d712d"
RYLE_PUBLIC_ROWS_SHA256 = "126427544212591cd4854b2e49d440182e57cffed2f24077065543aa2f9a4a7a"
RYLE_LICENSE = "Public domain (United States): identified pre-1901 Ryle text; 1952 imprint facts; CCEL electronic source credited, with reserved file and formatting restrictions"
SCHAFF6_ITEM = "schaff-history-vol-6--schaff-history-vol-6-retained-electronic-witness"
SCHAFF6_SCOPE_SHA256 = "87f7b0ad4801ed15d6fd0956910627d4fa3be513127f41955601ed977b2873e3"
SCHAFF6_PRIVATE_ROWS_SHA256 = "1d7c618ea60565cb7b02b712c32917a5fce83049b04a7ec7b213440c26a91c5c"
SCHAFF6_PUBLIC_ROWS_SHA256 = "974f27cb6469eb313eefffceef19cce0df3be8a378773a74d2cc8c6a56da0ed5"
SCHAFF6_LICENSE = "Public domain (United States): historical David S. Schaff volume 6 text; private CCEL electronic witness preparation, source-described 1910 Scribner edition, with reserved file and formatting rights"
SCHAFF6_FIELDS = {
    ("paragraph", "css_style", "margin-left:.5in;text-align:right;text-indent:-.25in"): None,
    ("paragraph", "css_style", "margin-left:.5in;text-align:right;text-indent:.5in"): None,
    ("paragraph", "css_style", "margin-left:2.25in"): None,
    ("paragraph", "css_style", "text-align:center"): None,
    ("paragraph", "css_style", "text-align:right"): None,
    ("paragraph", "css_style", "text-indent:0in"): None,
    ("segment", "css_style", "font-family:Gentium"): None,
    ("segment", "css_style", "font-style:normal"): "normal",
    ("source-block", "source_annotations", "source-css:text-indent:0in"): None,
}
HISTORICAL_FORMATTING_ITEMS = frozenset({
    "gregory-the-great-pastoral-rule-and-epistles--gregory-the-great-pastoral-rule-and-epistles-ccel-npnf212-electronic",
    "john-cassian-selected-works--john-cassian-selected-works-npnf211-electronic-witness",
    "sulpitius-severus-selected-works--sulpitius-severus-selected-works-npnf211-electronic-witness",
    "vincent-of-lerins-commonitory--vincent-of-lerins-commonitory-npnf211-electronic-witness",
})
HISTORICAL_ITEMS = {
    SCHAFF6_ITEM: (
        "3175c5bf2f6e579fd0429adda0bf4a605ab6374bf6ddac6fd74fce58873fae3f",
        "63c144dc5b51c9855c030d6e0f1e35dbdf890364aa2fb5643f24559be99c2555"),
    RYLE_ITEM: ("da5b3a57ab87242a19987b39c019d3a92ac3f154922423100d99285b52889a91",
                "fc84a9b758d566bbee7011e9cab517229973b50041d39d9a427a4b1f67294850"),
    EDWARDS_SELECT_ITEM: (
        "9e5aa76554b253bdf7d09b2825d2c8f0827f35e2da2fd6c17a1c6bbae5ee9b26",
        "10c21eab6f603b07b0116e5666d5d38f6383912b3806d5ab16ee433a7847bc92"),
    EDWARDS_ITEM: (
        "84ba0cc0fca7bcc6d803522a9f69116f7d87aa752959d53f7039bcf808c190d0",
        "2375aa5844ba313ed31bb849fce381884585676b24e13bcd3adc2f6dbb0908c8"),
    BENNETT_ITEM: ("977bd500d9f519177f968a0a6eeda83eccdf4ef1c7a41ac7231828c540422295",
                   "687ada6bf687e9727f2e95d76b8d66d96d1a9af7a2f04a20fe906cfd01a3e523"),
    "cyril-of-jerusalem-catechetical-lectures--cyril-of-jerusalem-catechetical-lectures-retained-electronic-witness": (
        "61ae4db4339c200f53bc04395d3277bc2b7b59a425877363a0a45308f710f7c5", "95c09f36e35d93d112859a3f449c80e90c19c1425aedf41d4a8a0a1ea2b4c17b"),
    "expositors-bible--g-a-chadwick--expositors-bible--g-a-chadwick-mark-retained-electronic": (
        "f818ac192a719f4a40fc350fd21113076374ea0cc796ea16a2fd5a6045233cf4", "d0c6a20dfe6bba8ee038d7d38f093af5d7a6bc49761e4b89a471101d81c5cc87"),
    "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness": (
        "76c12072e47967603b02e29b0abe8dc282fe053c69d32600e1debf252b2c943b", "dd7b1e192c76ac52844d72e281c49e3730b872a2a94bc10308bab994d9bab106"),
    "hodge-systematic-theology-vol-2--hodge-systematic-theology-vol-2-retained-electronic-witness": (
        "73e03fefcfc9a7173c49c20cd1969510b026a94b67897c4732c4727d6391da11", "f766c4e047e37f86d503c58b5c646d0d0d4ebd146288603c96685da755759e10"),
    "hodge-systematic-theology-vol-3--hodge-systematic-theology-vol-3-retained-electronic-witness": (
        "9043125267f8a083c0497223791fd18555c706e546b01c3f689f39a572cfc38b", "0ff6355e7f62163ec3879e7ce79491c7810e76267f486d27b1c877f749c628cb"),
    "ryle-expository-thoughts-matthew--ccel-matthew-electronic-witness": (
        "d0a014cbc6bf0c2605597332064b109902d5180f0fbf0376f9e66fe0172409e1", "df0d475814064f8084fcab998e17eb3e287c05af1a99c28db9e728b869405b67"),
    "gregory-the-great-pastoral-rule-and-epistles--gregory-the-great-pastoral-rule-and-epistles-ccel-npnf212-electronic": (
        "e97925a14b15d6d5a022651d31122f99f21b5e6844b27a2451be33d8f5dbd41b", "b87dcfd18ba3ddca7752d0c387eb82ac4668e1ad7921e2ddc74a91ea9e0021a1"),
    "john-cassian-selected-works--john-cassian-selected-works-npnf211-electronic-witness": (
        "aee89b7c704e8a1afa9a3e95d4accac840e35ae6b3176d08c863541bbe1eda47", "eaf4eb1aaf90cb00a19683c4e6b9e3d79295d0e211b199731a5c0d8507267008"),
    "sulpitius-severus-selected-works--sulpitius-severus-selected-works-npnf211-electronic-witness": (
        "60913d653a37e7959af6671a4351dc5657e0ce322c61cc3d243b5d02a8a45acf", "e568425bd72d93f052dd400a3df3ac18f4f1bbe0b36ee4c9ff3973f4209866bf"),
    "vincent-of-lerins-commonitory--vincent-of-lerins-commonitory-npnf211-electronic-witness": (
        "778ccaa54551145a6c043e50ad80ca0b5aa5b63dc6a17dfa510d92e02c968ff7", "c4c7ed8e98c0c07a3c782d08c12165e0a4d477b944426872d3784cda82df7d20"),
}
HODGE_ANNOTATIONS = {
    "hodge-systematic-theology-vol-1--hodge-systematic-theology-vol-1-retained-electronic-witness": "urn:ocd:hodge-theology1:ThML:",
    "hodge-systematic-theology-vol-2--hodge-systematic-theology-vol-2-retained-electronic-witness": "urn:ocd:hodge-theology2:ThML:",
}
HASH_BOUND_ITEMS = frozenset(HISTORICAL_ITEMS) | {aquinas_public.ITEM, watson_body_public.ITEM, GREEN_ITEM, FINNEY_ITEM, BOUNDS_ITEM, BUNYAN_ITEM, publick_worship.ITEM, form_church_government.ITEM, solemn_league.ITEM, sum_saving_knowledge.ITEM, bcp1662_public.ITEM, bcp1549_public.ITEM, bcp1559_public.ITEM, CHARNOCK_ITEM, CHARNOCK_V2_ITEM} | frozenset(PG_ITEMS) | {spurgeon_mtp_public.ITEM, catholic_encyclopedia_public.ITEM} | final_public_privacy.ITEMS
_OPAQUE_STYLE = re.compile(r"(?:[A-Za-z][A-Za-z0-9_-]*|class=[A-Za-z][A-Za-z0-9_-]*|(?:dir:(?:ltr|rtl);)?class:[A-Za-z][A-Za-z0-9:_-]*|source-class:[A-Za-z][A-Za-z0-9_-]*)\Z")
_SOURCE_TYPE = re.compile(r"(?:source-progress:[0-9]+(?:\.[0-9]+)?%(?:; source-type:[A-Za-z]+)?|source-type:[A-Za-z]+)\Z")
_CSS = re.compile(r"(?:^|[; |])(?:source-style[:=]|style[:=])?(?:border|font-(?:size|style|weight)|height|line-height|margin(?:-(?:left|right|top|bottom))?|tab-stops|text-align|text-indent|vertical-align|width)\s*[:=]", re.I)


def _digest(row: dict[str, Any]) -> str:
    return sha256(canonical_bytes(row)).hexdigest()


def _private_local_path(value: object) -> bool:
    """Recognize only a whole, whitespace-free path caught by the public scanner."""
    return (
        isinstance(value, str)
        and bool(value)
        and not any(character.isspace() for character in value)
        and _LOCAL_PATH.match(value) is not None
    )


def publication_transform_key(identity: dict) -> str:
    """Select source-specific publication behavior from accepted identity."""
    if not isinstance(identity, dict):
        raise PipelineError("publication transformation requires accepted identity")
    return "--".join(safe_identifier(identity.get(key), field=f"accepted {key}")
                     for key in ("work_id", "edition_id"))


def public_rows_with_omissions(
    rows: list[dict[str, Any]], *, item_id: str,
    acceptance_sha256: str | None = None, master_sha256: str | None = None,
    accepted_identity: dict | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Make authority-bound public rows and retain an exact private inverse."""
    accounting_item_id = item_id
    if accepted_identity is not None:
        # Historical artifacts keep this key; release manifests/paths account by item label.
        item_id = publication_transform_key(accepted_identity)
    if public_rights.uses_new_license(rows, item_id):
        return public_rights.public_rows(
            rows, item_id=item_id, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id in final_public_privacy.ITEMS:
        return final_public_privacy.public_rows(
            rows, item_id=item_id, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == catholic_encyclopedia_public.ITEM:
        return catholic_encyclopedia_public.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == spurgeon_mtp_public.ITEM:
        return spurgeon_mtp_public.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == aquinas_public.ITEM:
        return aquinas_public.public_rows(rows, acceptance_sha256=acceptance_sha256,
                                          master_sha256=master_sha256)
    if item_id == watson_body_public.ITEM:
        return watson_body_public.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == publick_worship.ITEM:
        return publick_worship.public_rows(rows, acceptance_sha256=acceptance_sha256,
                                          master_sha256=master_sha256)
    if item_id == form_church_government.ITEM:
        return form_church_government.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == solemn_league.ITEM:
        return solemn_league.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == sum_saving_knowledge.ITEM:
        return sum_saving_knowledge.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == bcp1662_public.ITEM:
        return bcp1662_public.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == bcp1559_public.ITEM:
        return bcp1559_public.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == bcp1549_public.ITEM:
        return bcp1549_public.public_rows(
            rows, acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == CHARNOCK_ITEM:
        return _charnock_rows(rows, acceptance_sha256, master_sha256)
    if item_id == EDWARDS_SELECT_ITEM:
        return _edwards_select_rows(rows, acceptance_sha256, master_sha256)
    if item_id == CHARNOCK_V2_ITEM:
        return _charnock_v2_rows(rows, acceptance_sha256, master_sha256)
    if item_id == FINNEY_ITEM:
        return _finney_rows(rows, acceptance_sha256, master_sha256)
    if item_id == SPURGEON_ITEM:
        return _spurgeon_rows(rows, acceptance_sha256, master_sha256)
    if item_id == EDWARDS_ITEM:
        return _edwards_rows(rows, acceptance_sha256, master_sha256)
    if item_id == BOUNDS_ITEM:
        return _bounds_rows(rows, acceptance_sha256, master_sha256)
    if item_id == BUNYAN_ITEM:
        return _bunyan_rows(rows, acceptance_sha256, master_sha256)
    if item_id == GREEN_ITEM:
        return _green_rows(rows, acceptance_sha256, master_sha256)
    if item_id in HISTORICAL_ITEMS:
        return _historical_rows(rows, item_id, acceptance_sha256, master_sha256)
    if item_id in PG_ITEMS:
        return _pg_rows(rows, item_id, acceptance_sha256, master_sha256)
    # Some projectors reuse one provenance mapping across rows. Copy each row
    # independently so removing a private path cannot mutate another output.
    public = [deepcopy(row) for row in rows]
    omissions = []
    for index, (original, row) in enumerate(zip(rows, public, strict=True)):
        provenance = row.get("provenance")
        if not isinstance(provenance, dict):
            continue
        location = provenance.get("source_location")
        if not _private_local_path(location):
            continue
        del provenance["source_location"]
        omissions.append({
            "row_index": index,
            "record_id": original.get("record_id"),
            "field": FIELD,
            "value": location,
            "original_row_sha256": _digest(original),
            "public_row_sha256": _digest(row),
        })
    if not omissions:
        return public, None
    return public, {
        "contract": CONTRACT,
        "item_id": accounting_item_id,
        "row_count": len(rows),
        "omissions": omissions,
    }


def restore_private_source_locations(
    rows: list[dict[str, Any]], artifact: dict[str, Any], *, item_id: str,
    acceptance_sha256: str | None = None, master_sha256: str | None = None,
    accepted_identity: dict | None = None,
) -> list[dict[str, Any]]:
    """Validate approved transforms and reconstruct independent checker input."""
    accounting_item_id = item_id
    if accepted_identity is not None:
        item_id = publication_transform_key(accepted_identity)
    if isinstance(artifact, dict) and artifact.get("contract") == public_rights.CONTRACT:
        return public_rights.restore(
            rows, artifact, item_id=item_id,
            acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id in final_public_privacy.ITEMS:
        return final_public_privacy.restore(
            rows, artifact, item_id=item_id,
            acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    if item_id == catholic_encyclopedia_public.ITEM:
        return catholic_encyclopedia_public.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == spurgeon_mtp_public.ITEM:
        return spurgeon_mtp_public.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == aquinas_public.ITEM:
        return aquinas_public.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == watson_body_public.ITEM:
        return watson_body_public.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == publick_worship.ITEM:
        return publick_worship.restore_private_rows(rows, artifact,
                                                   acceptance_sha256=acceptance_sha256,
                                                   master_sha256=master_sha256)
    if item_id == form_church_government.ITEM:
        return form_church_government.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == solemn_league.ITEM:
        return solemn_league.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == sum_saving_knowledge.ITEM:
        return sum_saving_knowledge.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == bcp1662_public.ITEM:
        return bcp1662_public.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == bcp1559_public.ITEM:
        return bcp1559_public.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == bcp1549_public.ITEM:
        return bcp1549_public.restore_private_rows(
            rows, artifact, acceptance_sha256=acceptance_sha256,
            master_sha256=master_sha256)
    if item_id == CHARNOCK_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != CHARNOCK_CONTRACT:
            raise PipelineError("Charnock volume I private source-ledger receipt required")
        return _restore_charnock(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == EDWARDS_SELECT_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != EDWARDS_SELECT_CONTRACT:
            raise PipelineError("Edwards Select Sermons private outline receipt required")
        return _restore_edwards_select(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == CHARNOCK_V2_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != CHARNOCK_V2_CONTRACT:
            raise PipelineError("Charnock volume II private source-ledger receipt required")
        return _restore_charnock_v2(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == FINNEY_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != FINNEY_CONTRACT:
            raise PipelineError("Finney historical public source-layer transform required")
        return _restore_finney(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == SPURGEON_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != SPURGEON_CONTRACT:
            raise PipelineError("Spurgeon public source-layer transform required")
        return _restore_spurgeon(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == EDWARDS_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != EDWARDS_CONTRACT:
            raise PipelineError("Edwards public source-layer transform required")
        return _restore_edwards(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == BOUNDS_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != BOUNDS_CONTRACT:
            raise PipelineError("Bounds historical-text transform required")
        return _restore_bounds(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == BUNYAN_ITEM:
        if not isinstance(artifact, dict) or artifact.get("contract") != BUNYAN_CONTRACT:
            raise PipelineError("Bunyan historical-text transform required")
        return _restore_bunyan(rows, artifact, acceptance_sha256, master_sha256)
    if item_id == GREEN_ITEM:
        return _restore_green(rows, artifact, acceptance_sha256, master_sha256)
    if item_id in HISTORICAL_ITEMS:
        if not isinstance(artifact, dict) or artifact.get("contract") != HISTORICAL_CONTRACT:
            raise PipelineError(f"{item_id}: historical public-row transform required")
        return _restore_historical(rows, artifact, item_id, acceptance_sha256, master_sha256)
    if item_id in PG_ITEMS:
        if not isinstance(artifact, dict) or artifact.get("contract") != PG_CONTRACT:
            raise PipelineError(f"{item_id}: PG public-row transform required")
        return _restore_pg(rows, artifact, item_id, acceptance_sha256, master_sha256)
    if isinstance(artifact, dict) and artifact.get("contract") == HISTORICAL_CONTRACT:
        return _restore_historical(rows, artifact, item_id, acceptance_sha256, master_sha256)
    if (
        not isinstance(artifact, dict)
        or set(artifact) != {"contract", "item_id", "row_count", "omissions"}
        or artifact["contract"] != CONTRACT
        or artifact["item_id"] != accounting_item_id
        or type(artifact["row_count"]) is not int
        or artifact["row_count"] != len(rows)
        or not isinstance(artifact["omissions"], list)
        or not artifact["omissions"]
    ):
        raise PipelineError("private public-row transform contract differs")
    restored = deepcopy(rows)
    previous = -1
    for omission in artifact["omissions"]:
        if not isinstance(omission, dict) or set(omission) != {
            "row_index", "record_id", "field", "value",
            "original_row_sha256", "public_row_sha256",
        }:
            raise PipelineError("unapproved public-row transform")
        index = omission["row_index"]
        if type(index) is not int or index <= previous or index >= len(rows):
            raise PipelineError("public-row transform index differs")
        previous = index
        public = rows[index]
        if (
            omission["field"] != FIELD
            or omission["record_id"] != public.get("record_id")
            or not _private_local_path(omission["value"])
            or omission["public_row_sha256"] != _digest(public)
        ):
            raise PipelineError("public-row transform binding differs")
        provenance = restored[index].get("provenance")
        if not isinstance(provenance, dict) or "source_location" in provenance:
            raise PipelineError("public-row source location was not omitted exactly once")
        provenance["source_location"] = omission["value"]
        if omission["original_row_sha256"] != _digest(restored[index]):
            raise PipelineError("restored public row differs from private binding")
    return restored


def _historical_authority(item_id: str, acceptance_sha256: str | None,
                          master_sha256: str | None) -> dict[str, str]:
    if (item_id not in HISTORICAL_ITEMS
            or (acceptance_sha256, master_sha256) != HISTORICAL_ITEMS[item_id]):
        raise PipelineError(f"{item_id}: historical formatting authority differs")
    evidence = ({"schaff6_scope_sha256": SCHAFF6_SCOPE_SHA256} if item_id == SCHAFF6_ITEM else
                {"ryle_scope_sha256": RYLE_SCOPE_SHA256} if item_id == RYLE_ITEM else
                {"edwards_select_scope_sha256": EDWARDS_SELECT_SCOPE_SHA256}
                if item_id == EDWARDS_SELECT_ITEM else
                {"bennett_scope_sha256": BENNETT_SCOPE_SHA256} if item_id == BENNETT_ITEM else
                {"formatting_scope_sha256": HISTORICAL_FORMATTING_SCOPE_SHA256}
                if item_id in HISTORICAL_FORMATTING_ITEMS
                else {"rights_disposition_sha256": HISTORICAL_RIGHTS_SHA256})
    return {"acceptance_sha256": acceptance_sha256,
            "master_sha256": master_sha256, **evidence}


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate source annotation key")
        result[key] = value
    return result


def _green_authority(acceptance_sha256: str | None, master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (GREEN_ACCEPTANCE_SHA256, GREEN_MASTER_SHA256):
        raise PipelineError("Green source-role public transform authority differs")
    return {"acceptance_sha256": GREEN_ACCEPTANCE_SHA256, "master_sha256": GREEN_MASTER_SHA256}


def _green_annotation(value: str, node: dict[str, Any]) -> str:
    if not isinstance(value, str) or not value.startswith(GREEN_PREFIX):
        raise PipelineError("unapproved Green source-role annotation")
    encoded = value.removeprefix(GREEN_PREFIX)
    try:
        source = json.loads(unquote(encoded, errors="strict"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise PipelineError("invalid Green source-role annotation") from exc
    if (not isinstance(source, dict) or list(source) != ["tag", "attributes"]
            or not isinstance(source["tag"], str) or not isinstance(source["attributes"], list)
            or quote(json.dumps(source, ensure_ascii=False, separators=(",", ":")), safe="") != encoded):
        raise PipelineError("Green source-role annotation shape differs")
    tag = source["tag"]
    expected = GREEN_ROLES.get(tag)
    attributes = node.get("attributes")
    if (expected is None or source["attributes"] != expected[1]
            or not isinstance(attributes, dict)
            or attributes.get("type") != expected[0]
            or attributes.get("subtype") != tag
            or (tag == "corr" and attributes.get("style") != "[space]")):
        raise PipelineError("Green source role and native semantic carrier differ")
    return "source-role:" + encoded


def _green_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _green_authority(acceptance_sha256, master_sha256)
    if (len(rows) != 13 or sha256(b"".join(canonical_bytes(row) for row in rows)).hexdigest()
            != GREEN_PRIVATE_ROWS_SHA256):
        raise PipelineError("Green private source-role row inventory differs")
    public = deepcopy(rows)
    rewritten = []
    for index, row in enumerate(public):
        fields = []

        def visit(value: Any, path: list[str | int]) -> None:
            if isinstance(value, list):
                for position, child in enumerate(value):
                    visit(child, path + [position])
            elif isinstance(value, dict):
                attributes = value.get("attributes")
                if ("kind" in value and isinstance(attributes, dict)
                        and isinstance(value.get("content"), list)
                        and "source_annotations" in attributes):
                    before = attributes["source_annotations"]
                    after = _green_annotation(before, value)
                    attributes["source_annotations"] = after
                    fields.append({"path": path + ["attributes", "source_annotations"],
                                   "private": before, "public": after})
                for key, child in value.items():
                    if key != "attributes":
                        visit(child, path + [key])

        visit(row, [])
        if fields:
            rewritten.append({"row_index": index, "record_id": row.get("record_id"),
                              "original_row_sha256": _digest(rows[index]),
                              "public_row_sha256": _digest(row), "fields": fields})
    if [(entry["row_index"], len(entry["fields"])) for entry in rewritten] != [(3, 8), (11, 1)]:
        raise PipelineError("Green public source-role inventory differs")
    return public, {"contract": GREEN_CONTRACT, "item_id": GREEN_ITEM,
                    "authority": authority, "row_count": len(rows), "rewrites": rewritten}


def _restore_green(rows: list[dict[str, Any]], artifact: dict[str, Any],
                   acceptance_sha256: str | None, master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _green_authority(acceptance_sha256, master_sha256)
    if (not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "row_count", "rewrites"}
            or artifact["contract"] != GREEN_CONTRACT or artifact["item_id"] != GREEN_ITEM
            or artifact["authority"] != authority or artifact["row_count"] != len(rows)
            or not isinstance(artifact["rewrites"], list)
            or not all(isinstance(x, dict) and type(x.get("row_index")) is int
                       and isinstance(x.get("fields"), list) for x in artifact["rewrites"])
            or [(x["row_index"], len(x["fields"])) for x in artifact["rewrites"]]
            != [(3, 8), (11, 1)]):
        raise PipelineError("Green public source-role receipt differs")
    restored = deepcopy(rows)
    for entry in artifact["rewrites"]:
        if (set(entry) != {"row_index", "record_id", "original_row_sha256",
                           "public_row_sha256", "fields"}
                or not isinstance(entry["fields"], list)):
            raise PipelineError("Green source-role receipt entry differs")
        index = entry["row_index"]
        row = restored[index]
        if entry["record_id"] != row.get("record_id") or entry["public_row_sha256"] != _digest(row):
            raise PipelineError("Green source-role public row differs")
        paths = set()
        for field in entry["fields"]:
            if (not isinstance(field, dict) or set(field) != {"path", "private", "public"}
                    or not isinstance(field["path"], list) or not field["path"]
                    or field["path"][-2:] != ["attributes", "source_annotations"]
                    or any(type(part) not in {str, int} for part in field["path"])):
                raise PipelineError("Green source-role field differs")
            path = tuple(field["path"])
            if path in paths:
                raise PipelineError("duplicate Green source-role field")
            paths.add(path)
            node: Any = row
            try:
                for part in field["path"][:-2]:
                    node = node[part]
            except (KeyError, IndexError, TypeError) as exc:
                raise PipelineError("Green source-role path differs") from exc
            if (not isinstance(node, dict) or not isinstance(node.get("content"), list)
                    or field["public"] != _green_annotation(field["private"], node)
                    or node.get("attributes", {}).get("source_annotations") != field["public"]):
                raise PipelineError("Green source-role public field differs")
            node["attributes"]["source_annotations"] = field["private"]
        if entry["original_row_sha256"] != _digest(row):
            raise PipelineError("restored Green source-role row differs")
    expected_public, expected_artifact = _green_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Green source-role receipt is incomplete")
    return restored


_BENNETT_ANNOTATION_KEYS = frozenset({
    "id", "class", "shownumber", "href", "shape",
    "%7Bhttp%3A%2F%2Fwww.w3.org%2FXML%2F1998%2Fnamespace%7Dlink",
    "n", "anchored", "place", "passage", "osisRef", "parsed", "style", "lang",
    "%7Bhttp%3A%2F%2Fwww.w3.org%2FXML%2F1998%2Fnamespace%7Dlang",
    "next", "prev", "title", "colspan", "rowspan", "type", "cellspacing", "summary", "span",
})
_BENNETT_STYLE = {
    "emphasis": "emphasis", "italic": "italic",
    "source-class-Centered": None, "source-class-Greek": "greek",
    "source-class-Hebrew": "hebrew", "source-class-Index": "index-heading",
    "source-class-Index1": "index-subheading", "source-class-TOC": "table-of-contents",
    "source-class-bbook": "biblical-book-name", "source-class-bref": "biblical-reference",
    "source-class-pages": None, "source-class-sc": "small-caps",
    "source-class-tei-cell": None, "source-class-tei-foreign": "foreign-language",
    "source-class-tei-hi": None, "source-h1": "heading-1",
    "source-h2": "heading-2", "source-h4": "heading-4",
}
_BENNETT_CSS = {
    "font-size: 173%": None, "font-size: 90%": None,
    "font-size: 90%; font-style: italic": "italic",
    "font-size: 90%; font-variant: small-caps": "small-caps",
    "font-style: italic": "italic", "margin-bottom: 0.90em": None,
    "margin-bottom: 1.00em": None, "text-align: left": None,
    "text-align: left; margin-bottom: 3.46em; margin-top: 3.46em": None,
    "width: 50%": None,
}

# Complete style inventory of the accepted Edwards ThML witness. These are
# presentation declarations only; literal Greek, emphasis, notes, and text
# remain in the native tree. Keep source class identifiers and small caps as
# semantic labels, without reproducing CCEL's font and alignment choices.
_EDWARDS_STYLE = {
    ("paragraph", "Centered"): "Centered",
    ("paragraph", "bbook"): "bbook",
    ("paragraph", "bref"): "bref",
    ("emphasis", "font-family:Gentium"): None,
    ("emphasis", "font-size:large"): None,
    ("emphasis", "font-size:x-small"): None,
    ("emphasis", "font-variant:small-caps"): "small-caps",
    ("paragraph", "footnote"): "footnote",
    ("emphasis", "italic"): "italic",
    ("paragraph", "text-align:justify"): None,
    ("paragraph", "title"): "title",
    ("paragraph", "title ; text-align:left"): "title",
    ("paragraph", "unindented"): "unindented",
}

# Exact Select Sermons native inventory. The list marker is semantic numbering;
# only layout lengths are omitted. Other source labels remain unchanged.
_EDWARDS_SELECT_STYLE = {
    ("division", "Index"): "Index",
    ("emphasis", "bold"): "bold",
    ("emphasis", "italic"): "italic",
    ("horizontal-rule", "width:50%"): None,
    ("list", "list-style-type:upper-roman"): "upper-roman",
    ("paragraph", "Centered"): "Centered",
    ("paragraph", "bbook"): "bbook",
    ("paragraph", "bref"): "bref",
    ("paragraph", "margin-left: 2em"): None,
    ("paragraph", "margin-left:4em"): None,
    ("paragraph", "margin-top:12pt"): None,
    ("paragraph", "sermon"): "sermon",
    ("paragraph", "sermonText"): "sermonText",
    ("source-block", "margin-left: 2em"): None,
    ("source-reference", "TOC"): "TOC",
}


def _edwards_select_style(value: str, kind: str) -> str | None:
    try:
        return _EDWARDS_SELECT_STYLE[kind, value]
    except KeyError as exc:
        raise PipelineError("Edwards Select Sermons source style inventory differs") from exc


def _edwards_style(value: str, kind: str) -> str | None:
    try:
        return _EDWARDS_STYLE[kind, value]
    except KeyError as exc:
        raise PipelineError("Edwards accepted source presentation differs") from exc


def _bennett_annotation(value: str) -> None:
    parts = value.split(" ")
    if not parts or any(not part for part in parts):
        raise PipelineError("Bennett source annotation shape differs")
    for part in parts:
        match = re.fullmatch(r"urn:ccel:source-attribute:([^: ]+):([^: ]*)", part)
        if match is None or match[1] not in _BENNETT_ANNOTATION_KEYS:
            raise PipelineError("Bennett source annotation token differs")
        try:
            decoded = unquote(match[2], errors="strict")
        except UnicodeError as exc:
            raise PipelineError("Bennett source annotation encoding differs") from exc
        if quote(decoded, safe="") != match[2]:
            raise PipelineError("Bennett source annotation encoding differs")
    # Literal CCEL source metadata remains in the exact private inverse and master.
    return None


def _bennett_style(value: str, key: str) -> str | None:
    mapping = _BENNETT_STYLE if key == "style" else _BENNETT_CSS
    if value not in mapping:
        raise PipelineError("Bennett source presentation differs")
    return mapping[value]


def _public_annotation(value: str, item_id: str) -> str | None:
    if item_id == SCHAFF6_ITEM:
        return _schaff6_field("source-block", "source_annotations", value)
    if item_id == BENNETT_ITEM:
        return _bennett_annotation(value)
    prefix = HODGE_ANNOTATIONS.get(item_id)
    if prefix is None or not value.startswith(prefix):
        raise PipelineError(f"{item_id}: unapproved source annotation")
    encoded = value.removeprefix(prefix)
    try:
        source = json.loads(unquote(encoded, errors="strict"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise PipelineError("invalid Hodge source annotation") from exc
    if (not isinstance(source, dict) or list(source) != ["tag", "attributes"]
            or not isinstance(source["tag"], str)
            or not isinstance(source["attributes"], list)
            or quote(json.dumps(source, ensure_ascii=False, separators=(",", ":")), safe="") != encoded):
        raise PipelineError("Hodge source annotation shape differs")
    pairs = source["attributes"]
    if (any(not isinstance(pair, list) or len(pair) != 2
            or any(not isinstance(part, str) for part in pair) for pair in pairs)
            or len({pair[0] for pair in pairs}) != len(pairs)
            or any(pair[0] not in {"border", "class", "colspan", "href", "id", "lang", "n",
                                    "next", "osisRef", "parsed", "passage", "prev", "progress",
                                    "rowspan", "style", "title", "type"} for pair in pairs)):
        raise PipelineError("Hodge source annotation attributes differ")
    # Only these two literal presentation attributes leave the typed source record.
    source["attributes"] = [pair for pair in pairs if pair[0] not in {"border", "style"}]
    return "source-annotation:" + quote(
        json.dumps(source, ensure_ascii=False, separators=(",", ":")), safe="")


def _public_style(value: str, kind: str) -> str | None:
    if _OPAQUE_STYLE.fullmatch(value) or _SOURCE_TYPE.fullmatch(value):
        return value
    # The accepted Chadwick Mark master has one class/layout composite. Keep
    # its source class while omitting only the source margin declaration.
    if value == "source-class:SectionInfo2; source-style:margin-top:9pt":
        return "source-class:SectionInfo2"
    if kind in {"gap", "text"}:
        raise PipelineError("semantic native content style cannot be omitted")
    if value == "100%":
        return None
    if not _CSS.search(value):
        raise PipelineError(f"unclassified native presentation: {value}")
    prefix = re.match(r"([A-Za-z][A-Za-z0-9_-]*)\s+(?:\||(?=width\s*:))", value)
    if prefix:
        return prefix[1]
    if re.search(r"font-style\s*:\s*italic\b", value, re.I):
        return "italic"
    if re.search(r"font-weight\s*:\s*bold\b", value, re.I):
        return "bold"
    return None


def _schaff6_field(kind: str, key: str, value: str) -> str | None:
    field = (kind, key, value)
    if field not in SCHAFF6_FIELDS:
        raise PipelineError("Schaff volume 6 private presentation differs")
    return SCHAFF6_FIELDS[field]


def _historical_rows(rows: list[dict[str, Any]], item_id: str,
                     acceptance_sha256: str | None, master_sha256: str | None
                     ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    authority = _historical_authority(item_id, acceptance_sha256, master_sha256)
    if item_id == RYLE_ITEM and (len(rows) != 4 or _digest(rows) != RYLE_PRIVATE_ROWS_SHA256
                             or any(row.get("license") != RYLE_LICENSE for row in rows)):
        raise PipelineError("Ryle accepted four-unit historical scope differs")
    if item_id == SCHAFF6_ITEM and (len(rows) != 4 or _digest(rows) != SCHAFF6_PRIVATE_ROWS_SHA256
                               or any(row.get("license") != SCHAFF6_LICENSE for row in rows)):
        raise PipelineError("Schaff volume 6 private accepted scope differs")
    public = deepcopy(rows)
    omissions = []
    for index, row in enumerate(public):
        fields = []

        def change(path: list[str | int], attributes: dict, key: str, after: str | None) -> None:
            before = attributes[key]
            if after == before:
                return
            fields.append({"path": path + [key], "private": before, "public": after})
            if after is None:
                del attributes[key]
            else:
                attributes[key] = after

        provenance = row.get("provenance")
        if isinstance(provenance, dict) and _private_local_path(provenance.get("source_location")):
            change(["provenance"], provenance, "source_location", None)

        def visit(value: Any, path: list[str | int]) -> None:
            if isinstance(value, list):
                for position, child in enumerate(value):
                    visit(child, path + [position])
            elif isinstance(value, dict):
                attributes = value.get("attributes")
                if "kind" in value and isinstance(attributes, dict) and isinstance(value.get("content"), list):
                    for key in ("source_annotations", "style", "css_style"):
                        if key not in attributes:
                            continue
                        before = attributes[key]
                        if not isinstance(before, str):
                            raise PipelineError("native presentation must be a string")
                        if item_id == SCHAFF6_ITEM and key in {"css_style", "source_annotations"}:
                            after = _schaff6_field(value["kind"], key, before)
                        elif key == "source_annotations":
                            after = _public_annotation(before, item_id)
                        else:
                            after = (_edwards_select_style(before, value["kind"])
                                     if item_id == EDWARDS_SELECT_ITEM else
                                     _bennett_style(before, key) if item_id == BENNETT_ITEM else
                                     _edwards_style(before, value["kind"])
                                     if item_id == EDWARDS_ITEM else
                                     _public_style(before, value["kind"]))
                        change(path + ["attributes"], attributes, key, after)
                for key, child in value.items():
                    if key != "attributes":
                        visit(child, path + [key])

        visit(row, [])
        if fields:
            omissions.append({"row_index": index, "record_id": row.get("record_id"),
                              "original_row_sha256": _digest(rows[index]),
                              "public_row_sha256": _digest(row), "fields": fields})
    if item_id == RYLE_ITEM and (sum(len(entry["fields"]) for entry in omissions) != 7
                             or any(field["path"][-1] != "style" or field["public"] is not None
                                    for entry in omissions for field in entry["fields"])
                             or _digest(public) != RYLE_PUBLIC_ROWS_SHA256):
        raise PipelineError("Ryle seven-field public presentation inventory differs")
    if item_id == SCHAFF6_ITEM and (sum(len(entry["fields"]) for entry in omissions) != 14
                                or _digest(public) != SCHAFF6_PUBLIC_ROWS_SHA256):
        raise PipelineError("Schaff volume 6 public presentation inventory differs")
    if not omissions:
        return public, None
    return public, {"contract": HISTORICAL_CONTRACT, "item_id": item_id,
                    "authority": authority, "row_count": len(rows), "omissions": omissions}


def _restore_historical(rows: list[dict[str, Any]], artifact: dict[str, Any],
                        item_id: str, acceptance_sha256: str | None,
                        master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _historical_authority(item_id, acceptance_sha256, master_sha256)
    if (set(artifact) != {"contract", "item_id", "authority", "row_count", "omissions"}
            or artifact["item_id"] != item_id or artifact["authority"] != authority
            or type(artifact["row_count"]) is not int or artifact["row_count"] != len(rows)
            or not isinstance(artifact["omissions"], list) or not artifact["omissions"]):
        raise PipelineError("historical public-row transform contract differs")
    restored = deepcopy(rows)
    previous = -1
    for entry in artifact["omissions"]:
        if (not isinstance(entry, dict)
                or set(entry) != {"row_index", "record_id", "original_row_sha256",
                                  "public_row_sha256", "fields"}
                or type(entry["row_index"]) is not int
                or not previous < entry["row_index"] < len(rows)
                or not isinstance(entry["fields"], list) or not entry["fields"]):
            raise PipelineError("historical public-row transform entry differs")
        index = entry["row_index"]
        previous = index
        row = restored[index]
        if entry["record_id"] != row.get("record_id") or entry["public_row_sha256"] != _digest(row):
            raise PipelineError("historical public-row transform binding differs")
        used = set()
        for field in entry["fields"]:
            if (not isinstance(field, dict) or set(field) != {"path", "private", "public"}
                    or not isinstance(field["path"], list) or not field["path"]
                    or any(type(part) not in {str, int} for part in field["path"])
                    or not isinstance(field["private"], str)):
                raise PipelineError("historical public-row field differs")
            path = field["path"]
            if tuple(path) in used:
                raise PipelineError("duplicate historical public-row field")
            used.add(tuple(path))
            holder: Any = row
            try:
                for part in path[:-1]:
                    holder = holder[part]
            except (KeyError, IndexError, TypeError) as exc:
                raise PipelineError("historical public-row field path differs") from exc
            key = path[-1]
            if not isinstance(holder, dict) or not isinstance(key, str):
                raise PipelineError("historical public-row field target differs")
            if path == ["provenance", "source_location"]:
                expected = None if _private_local_path(field["private"]) else field["private"]
            elif len(path) >= 2 and path[-2] == "attributes" and key in {
                    "source_annotations", "style", "css_style"}:
                node: Any = row
                for part in path[:-2]:
                    node = node[part]
                if not isinstance(node, dict) or not isinstance(node.get("content"), list):
                    raise PipelineError("historical native node differs")
                expected = (_schaff6_field(node.get("kind"), key, field["private"])
                            if item_id == SCHAFF6_ITEM and key in {"css_style", "source_annotations"} else
                            _public_annotation(field["private"], item_id)
                            if key == "source_annotations" else
                            _edwards_select_style(field["private"], node.get("kind"))
                            if item_id == EDWARDS_SELECT_ITEM else
                            _bennett_style(field["private"], key) if item_id == BENNETT_ITEM else
                            _edwards_style(field["private"], node.get("kind"))
                            if item_id == EDWARDS_ITEM else
                            _public_style(field["private"], node.get("kind")))
            else:
                raise PipelineError("unapproved historical public-row field")
            if (field["public"] != expected
                    or (expected is None and key in holder)
                    or (expected is not None and holder.get(key) != expected)):
                raise PipelineError("historical public-row field binding differs")
            holder[key] = field["private"]
        if entry["original_row_sha256"] != _digest(row):
            raise PipelineError("restored historical row differs from private binding")
    expected_public, expected_artifact = _historical_rows(
        restored, item_id, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("historical public-row omissions are incomplete")
    return restored


def _edwards_select_content(row: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        unit = row["structure"][0]
        content = unit["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Edwards Select Sermons source unit differs") from exc
    if (unit.get("kind") != "division"
            or unit.get("attributes") != {
                "number": "God's Sovereignty in the Salvation of Men", "type": "source-div1"}
            or not isinstance(content, list)):
        raise PipelineError("Edwards Select Sermons source unit differs")
    return content


def _edwards_select_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                         master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep Edwards's sermon; omit the contributor outline and exact CCEL layout."""
    authority = _historical_authority(EDWARDS_SELECT_ITEM, acceptance_sha256,
                                      master_sha256)
    if (len(rows) != 21
            or any(row.get("license") != EDWARDS_SELECT_LICENSE for row in rows)
            or sha256(canonical_bytes(rows)).hexdigest() != EDWARDS_SELECT_PRIVATE_ROWS_SHA256):
        raise PipelineError("Edwards Select Sermons accepted private rows differ")
    from ocd_kernel.projection.native_content import readable_content

    intermediate = deepcopy(rows)
    row = intermediate[4]
    content = _edwards_select_content(row)
    if (row.get("record_id") != "edwards-select-sermons-ccel-thml-electronic:native:29fc603679ee31a722bc"
            or len(content) != 103
            or sha256(canonical_bytes(content[13])).hexdigest()
            != EDWARDS_SELECT_NOTICE_NODE_SHA256
            or sha256(canonical_bytes(content[29])).hexdigest()
            != EDWARDS_SELECT_OUTLINE_NODE_SHA256
            or row.get("text") != readable_content(row["structure"][0])):
        raise PipelineError("Edwards Select Sermons contributor outline differs")
    outline = content.pop(29)
    notice = content.pop(13)
    row["text"] = readable_content(row["structure"][0])
    public, inner = _historical_rows(intermediate, EDWARDS_SELECT_ITEM,
                                     acceptance_sha256, master_sha256)
    if inner is None:
        raise PipelineError("Edwards Select Sermons layout receipt absent")
    styles = {}
    for entry in inner["omissions"]:
        for field in entry["fields"]:
            if field["path"][-2:] == ["attributes", "style"]:
                key = field["private"]
                styles[key] = styles.get(key, 0) + 1
    if styles != {"width:50%": 2, "margin-left: 2em": 4,
                  "margin-left:4em": 1, "margin-top:12pt": 17,
                  "list-style-type:upper-roman": 1}:
        raise PipelineError("Edwards Select Sermons source layout inventory differs")
    if (_scan(public, "Edwards Select Sermons public rows")
            or "An outline of the sermon has been prepared" in public[4]["text"]
            or "click on a Roman Numeral" in public[4]["text"]):
        raise PipelineError("Edwards Select Sermons public outline remains")
    return public, {"contract": EDWARDS_SELECT_CONTRACT,
                    "item_id": EDWARDS_SELECT_ITEM, "authority": authority,
                    "private_rows_sha256": EDWARDS_SELECT_PRIVATE_ROWS_SHA256,
                    "public_rows_sha256": sha256(canonical_bytes(public)).hexdigest(),
                    "removed_notice": notice, "removed_outline": outline,
                    "inner": inner}


def _restore_edwards_select(rows: list[dict[str, Any]], artifact: dict[str, Any],
                            acceptance_sha256: str | None,
                            master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _historical_authority(EDWARDS_SELECT_ITEM, acceptance_sha256,
                                      master_sha256)
    if (len(rows) != 21
            or set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                                 "public_rows_sha256", "removed_notice", "removed_outline", "inner"}
            or artifact["item_id"] != EDWARDS_SELECT_ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != EDWARDS_SELECT_PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != sha256(canonical_bytes(rows)).hexdigest()
            or sha256(canonical_bytes(artifact["removed_notice"])).hexdigest()
            != EDWARDS_SELECT_NOTICE_NODE_SHA256
            or sha256(canonical_bytes(artifact["removed_outline"])).hexdigest()
            != EDWARDS_SELECT_OUTLINE_NODE_SHA256):
        raise PipelineError("Edwards Select Sermons source-layer receipt differs")
    from ocd_kernel.projection.native_content import readable_content

    intermediate = _restore_historical(rows, artifact["inner"], EDWARDS_SELECT_ITEM,
                                       acceptance_sha256, master_sha256)
    restored = deepcopy(intermediate)
    row = restored[4]
    content = _edwards_select_content(row)
    if len(content) != 101 or row.get("text") != readable_content(row["structure"][0]):
        raise PipelineError("Edwards Select Sermons public structure differs")
    content.insert(13, deepcopy(artifact["removed_notice"]))
    content.insert(29, deepcopy(artifact["removed_outline"]))
    row["text"] = readable_content(row["structure"][0])
    if sha256(canonical_bytes(restored)).hexdigest() != EDWARDS_SELECT_PRIVATE_ROWS_SHA256:
        raise PipelineError("Edwards Select Sermons private inverse differs")
    expected_public, expected_artifact = _edwards_select_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Edwards Select Sermons public omissions are incomplete")
    return restored


def _edwards_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                  master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Omit the modern cover-art notice; retain the historical text and factual index."""
    authority = _historical_authority(EDWARDS_ITEM, acceptance_sha256, master_sha256)
    if (len(rows) != 8 or any(row.get("license") != EDWARDS_LICENSE for row in rows)
            or _digest(rows[6]) != EDWARDS_ACK_ROW_SHA256
            or _digest({key: value for key, value in rows[6].items() if key != "license"})
            != EDWARDS_ACK_SOURCE_ROW_SHA256
            or rows[6].get("record_id") != "ccel-thml-electronic-witness:native:c9e89088f007f2ccd3e7"
            or not rows[7].get("text", "").startswith("Indexes\n\nIndex of Scripture References")):
        raise PipelineError("Edwards accepted cover-art or scripture-index source row differs")
    retained = [deepcopy(row) for index, row in enumerate(rows) if index != 6]
    public, inner = _historical_rows(retained, EDWARDS_ITEM,
                                     acceptance_sha256, master_sha256)
    if inner is None:
        raise PipelineError("Edwards historical presentation omissions required")
    return public, {"contract": EDWARDS_CONTRACT, "item_id": EDWARDS_ITEM,
                    "authority": authority, "private_row_count": 8,
                    "public_row_count": 7, "removed_row_index": 6,
                    "removed_row": deepcopy(rows[6]), "inner": inner}


def _restore_edwards(rows: list[dict[str, Any]], artifact: dict[str, Any],
                     acceptance_sha256: str | None,
                     master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _historical_authority(EDWARDS_ITEM, acceptance_sha256, master_sha256)
    if (len(rows) != 7
            or set(artifact) != {"contract", "item_id", "authority", "private_row_count",
                                 "public_row_count", "removed_row_index", "removed_row", "inner"}
            or artifact["contract"] != EDWARDS_CONTRACT
            or artifact["item_id"] != EDWARDS_ITEM or artifact["authority"] != authority
            or artifact["private_row_count"] != 8 or artifact["public_row_count"] != 7
            or artifact["removed_row_index"] != 6
            or not isinstance(artifact["removed_row"], dict)
            or _digest(artifact["removed_row"]) != EDWARDS_ACK_ROW_SHA256):
        raise PipelineError("Edwards public cover-art omission receipt differs")
    retained = _restore_historical(rows, artifact["inner"], EDWARDS_ITEM,
                                    acceptance_sha256, master_sha256)
    restored = deepcopy(retained)
    restored.insert(6, deepcopy(artifact["removed_row"]))
    expected_public, expected_artifact = _edwards_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Edwards public source-layer omissions are incomplete")
    return restored


def _bunyan_authority(acceptance_sha256: str | None,
                      master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (BUNYAN_ACCEPTANCE_SHA256,
                                                BUNYAN_MASTER_SHA256):
        raise PipelineError("Bunyan accepted historical-text authority differs")
    return {"acceptance_sha256": BUNYAN_ACCEPTANCE_SHA256,
            "master_sha256": BUNYAN_MASTER_SHA256}


def _bunyan_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                 master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep the author's text and index; omit the distinct modern publisher foreword."""
    from ocd_kernel.projection.native_content import readable_content

    authority = _bunyan_authority(acceptance_sha256, master_sha256)
    if (len(rows) != 1 or rows[0].get("license") != BUNYAN_LICENSE
            or _digest(rows[0]) != BUNYAN_PRIVATE_ROW_SHA256):
        raise PipelineError("Bunyan selected private row differs")
    public = deepcopy(rows)
    content = public[0]["structure"][0]["content"]
    if (len(content) != 16 or _digest(content[2]) != BUNYAN_FOREWORD_SHA256
            or _digest(content[3]) != BUNYAN_SEPARATOR_SHA256):
        raise PipelineError("Bunyan publisher foreword unit differs")
    removed = deepcopy(content[2:4])
    del content[2:4]
    public[0]["text"] = readable_content(public[0]["structure"][0])
    if _digest(public[0]) != BUNYAN_PUBLIC_ROW_SHA256:
        raise PipelineError("Bunyan historical public row differs")
    return public, {"contract": BUNYAN_CONTRACT, "item_id": BUNYAN_ITEM,
                    "authority": authority, "private_row_sha256": BUNYAN_PRIVATE_ROW_SHA256,
                    "public_row_sha256": BUNYAN_PUBLIC_ROW_SHA256,
                    "removed_index": 2, "removed": removed}


def _restore_bunyan(rows: list[dict[str, Any]], artifact: dict[str, Any],
                    acceptance_sha256: str | None,
                    master_sha256: str | None) -> list[dict[str, Any]]:
    from ocd_kernel.projection.native_content import readable_content

    authority = _bunyan_authority(acceptance_sha256, master_sha256)
    if (len(rows) != 1 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_row_sha256",
                                 "public_row_sha256", "removed_index", "removed"}
            or artifact["contract"] != BUNYAN_CONTRACT or artifact["item_id"] != BUNYAN_ITEM
            or artifact["authority"] != authority
            or artifact["private_row_sha256"] != BUNYAN_PRIVATE_ROW_SHA256
            or artifact["public_row_sha256"] != BUNYAN_PUBLIC_ROW_SHA256
            or artifact["removed_index"] != 2
            or _digest(rows[0]) != BUNYAN_PUBLIC_ROW_SHA256
            or not isinstance(artifact["removed"], list)
            or len(artifact["removed"]) != 2
            or _digest(artifact["removed"][0]) != BUNYAN_FOREWORD_SHA256
            or _digest(artifact["removed"][1]) != BUNYAN_SEPARATOR_SHA256):
        raise PipelineError("Bunyan public foreword omission receipt differs")
    restored = deepcopy(rows)
    content = restored[0]["structure"][0]["content"]
    if len(content) != 14:
        raise PipelineError("Bunyan public source-unit inventory differs")
    content[2:2] = deepcopy(artifact["removed"])
    restored[0]["text"] = readable_content(restored[0]["structure"][0])
    if _digest(restored[0]) != BUNYAN_PRIVATE_ROW_SHA256:
        raise PipelineError("Bunyan restored private row differs")
    expected_public, expected_artifact = _bunyan_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Bunyan public historical-text omission is incomplete")
    return restored


def _bounds_authority(acceptance_sha256: str | None,
                      master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256, master_sha256) != (BOUNDS_ACCEPTANCE_SHA256,
                                                BOUNDS_MASTER_SHA256):
        raise PipelineError("Bounds accepted historical-text authority differs")
    return {"acceptance_sha256": BOUNDS_ACCEPTANCE_SHA256,
            "master_sha256": BOUNDS_MASTER_SHA256}


def _bounds_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                 master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Omit only the two unattested promotional paragraphs before chapter one."""
    from ocd_kernel.projection.native_content import readable_content

    authority = _bounds_authority(acceptance_sha256, master_sha256)
    if (len(rows) != 1 or rows[0].get("license") != BOUNDS_LICENSE
            or _digest(rows[0]) != BOUNDS_PRIVATE_ROW_SHA256):
        raise PipelineError("Bounds selected private row differs")
    public = deepcopy(rows)
    front = public[0]["structure"][0]["content"][0]["content"]
    if (len(front) != 23 or any(front[index].get("kind") != "paragraph"
            or _digest(front[index]) != expected
            for index, expected in BOUNDS_PROMOTIONAL_PARAGRAPHS.items())):
        raise PipelineError("Bounds promotional source paragraphs differ")
    removed = [{"index": index, "node": deepcopy(front[index]), "sha256": expected}
               for index, expected in BOUNDS_PROMOTIONAL_PARAGRAPHS.items()]
    for index in sorted(BOUNDS_PROMOTIONAL_PARAGRAPHS, reverse=True):
        del front[index]
    public[0]["text"] = readable_content(public[0]["structure"][0])
    if _digest(public[0]) != BOUNDS_PUBLIC_ROW_SHA256:
        raise PipelineError("Bounds historical public row differs")
    return public, {"contract": BOUNDS_CONTRACT, "item_id": BOUNDS_ITEM,
                    "authority": authority, "private_row_sha256": BOUNDS_PRIVATE_ROW_SHA256,
                    "public_row_sha256": BOUNDS_PUBLIC_ROW_SHA256, "removed": removed}


def _restore_bounds(rows: list[dict[str, Any]], artifact: dict[str, Any],
                    acceptance_sha256: str | None,
                    master_sha256: str | None) -> list[dict[str, Any]]:
    from ocd_kernel.projection.native_content import readable_content

    authority = _bounds_authority(acceptance_sha256, master_sha256)
    if (len(rows) != 1 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority",
                                 "private_row_sha256", "public_row_sha256", "removed"}
            or artifact["contract"] != BOUNDS_CONTRACT
            or artifact["item_id"] != BOUNDS_ITEM or artifact["authority"] != authority
            or artifact["private_row_sha256"] != BOUNDS_PRIVATE_ROW_SHA256
            or artifact["public_row_sha256"] != BOUNDS_PUBLIC_ROW_SHA256
            or _digest(rows[0]) != BOUNDS_PUBLIC_ROW_SHA256
            or not isinstance(artifact["removed"], list)
            or len(artifact["removed"]) != len(BOUNDS_PROMOTIONAL_PARAGRAPHS)):
        raise PipelineError("Bounds public omission receipt differs")
    restored = deepcopy(rows)
    front = restored[0]["structure"][0]["content"][0]["content"]
    if len(front) != 21:
        raise PipelineError("Bounds public front matter differs")
    for entry, (index, expected) in zip(artifact["removed"],
                                        BOUNDS_PROMOTIONAL_PARAGRAPHS.items(), strict=True):
        if (not isinstance(entry, dict) or set(entry) != {"index", "node", "sha256"}
                or entry["index"] != index or entry["sha256"] != expected
                or not isinstance(entry["node"], dict)
                or _digest(entry["node"]) != expected):
            raise PipelineError("Bounds omitted paragraph receipt differs")
        front.insert(index, deepcopy(entry["node"]))
    restored[0]["text"] = readable_content(restored[0]["structure"][0])
    if _digest(restored[0]) != BOUNDS_PRIVATE_ROW_SHA256:
        raise PipelineError("Bounds restored private row differs")
    expected_public, expected_artifact = _bounds_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Bounds public historical-text omission is incomplete")
    return restored


_PG_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_PG_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_PG_ATTRIBUTE_KEYS = frozenset({"type", "n", _PG_XML_ID, _PG_XML_LANG, "rend",
                                "unit", "url", "cols", "role"})
_PG_DIGEST_TOKEN = re.compile(
    r"(?:presentation-style-omitted-sha256|comment-digest):[0-9a-f]{64}\Z"
)
_PG_IMAGE_MEMBER = re.compile(r"images/[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|gif)\Z", re.I)
_JARENA_IMAGE = re.compile(
    r"raw/gutenberg/66953/html/images/([A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|gif))\Z", re.I
)


def _pg_authority(item_id: str, acceptance_sha256: str | None,
                  master_sha256: str | None) -> dict[str, str]:
    if (item_id not in PG_ITEMS
            or (acceptance_sha256, master_sha256) != PG_ITEMS[item_id]):
        raise PipelineError(f"{item_id}: PG public-row authority differs")
    authority = {"acceptance_sha256": acceptance_sha256,
                 "master_sha256": master_sha256}
    if item_id == "louise-imogen-guiney-blessed-edmund-campion--pg52731-1914":
        authority["campion_scope_packet_sha256"] = (
            "18f656f70d0d3f8847c2120769384dd5a6d8e6b90638efb818abc57fb29397e7"
        )
    elif item_id == PG42957_ITEM:
        authority["pg42957_scope_evidence_sha256"] = (
            "88b7c587c973cd320ba08c7ac6469de0eaf4db4be843b82a611b252062d21fa5"
        )
    elif item_id == NEWMAN_ITEM:
        authority["newman_scope_evidence_sha256"] = "8723c6e9f29e0c54d4ba62c7f29766c2e4117e9e6097ec09e37ccbcfed5665ce"
    elif item_id == NOAH_ITEM:
        authority["noah_scope_packet_sha256"] = "9053947dced17b6312584dac29940f8e2c900446cdedc38e60bce60e5af79453"
    elif item_id == SPURGEON_ITEM:
        authority["spurgeon_scope_evidence_sha256"] = SPURGEON_SCOPE_SHA256
    elif item_id == TERESA_ITEM:
        authority["teresa_scope_evidence_sha256"] = "ba10273e107a6da5105cf2370f84a1f1f7a87118e35c209d07b34dc8877b2863"
    else:
        authority["pg52_review_candidate_sha256"] = (
            "3bcf0d1b6a1ef0b45b29f6776c13c941a818ea2468f5c606ddbb1706fdd01473"
        )
    return authority


def _pg_strip_digest(value: str) -> str | None:
    """Remove only exact source bookkeeping tokens; keep labels and classes."""
    if not isinstance(value, str):
        raise PipelineError("PG source rendition is not a string")
    parts = value.split(" ")
    if not any(_PG_DIGEST_TOKEN.fullmatch(part) for part in parts):
        return value
    kept = [part for part in parts if not _PG_DIGEST_TOKEN.fullmatch(part)]
    result = " ".join(kept).strip(" ")
    return result or None


def _pg_pairs(value: object) -> list[list[str]]:
    if (not isinstance(value, list) or any(
            not isinstance(pair, list) or len(pair) != 2
            or not all(isinstance(part, str) for part in pair)
            for pair in value)):
        raise PipelineError("PG source attribute pairs differ")
    if len({pair[0] for pair in value}) != len(value):
        raise PipelineError("duplicate PG source attribute")
    output = []
    for key, original in value:
        if key not in _PG_ATTRIBUTE_KEYS:
            raise PipelineError(f"unclassified PG source attribute: {key}")
        public = _pg_strip_digest(original) if key == "rend" else original
        if public is not None:
            if _scan(public, "PG source attribute"):
                raise PipelineError("private PG source attribute cannot be public")
            output.append([key, public])
    return output


def _pg_noah_image_pairs(source: object) -> tuple[list[list[str]], str, str]:
    """Expose only the source-attested image member, never the embedded JPEG."""
    keys = ["n", _PG_XML_ID, "url", "rend", "corresp"]
    if (not isinstance(source, list) or len(source) != len(keys)
            or any(not isinstance(pair, list) or len(pair) != 2
                   or not all(isinstance(part, str) for part in pair)
                   for pair in source)
            or [pair[0] for pair in source] != keys):
        raise PipelineError("Noah Davis source image annotation differs")
    attrs = dict(source)
    target, member = attrs["url"], attrs["corresp"]
    if (not re.fullmatch(r"data:image/jpeg;base64,[A-Za-z0-9+/=]+", target)
            or member != "images/church.jpg"
            or attrs["rend"] != "source-alt:church (52K)"):
        raise PipelineError("Noah Davis source image authority differs")
    safe = _pg_pairs(source[:2] + source[3:4]) + [["corresp", member]]
    return safe, target, member


def _pg_annotation(value: str, item_id: str) -> str:
    if item_id == SPURGEON_ITEM and value == SPURGEON_MARKER:
        return SPURGEON_PUBLIC_MARKER
    if item_id == TERESA_ITEM and value == TERESA_PRIVATE_ANNOTATION:
        return TERESA_PUBLIC_ANNOTATION
    if item_id == NEWMAN_ITEM and value == NEWMAN_GREEK_MARKER:
        return NEWMAN_PUBLIC_MARKER
    if item_id in PG_ORDINAL_ITEMS and value.startswith("urn:ocd:source-ordinal:"):
        ordinal = value.removeprefix("urn:ocd:source-ordinal:")
        if not re.fullmatch(r"[1-9][0-9]*", ordinal):
            raise PipelineError("PG source ordinal differs")
        return "source-ordinal:" + ordinal
    if (item_id == "keble-christian-year--keble-christian-year-gutenberg-electronic"
            and value.startswith("urn:ocd:source-alt-and-title:")):
        encoded = value.removeprefix("urn:ocd:source-alt-and-title:")
        label = unquote(encoded, errors="strict")
        if not label or quote(label) != encoded or _scan(label, "PG image label"):
            raise PipelineError("PG source alt/title label differs")
        return "source-alt-and-title:" + label
    prefix = (
        "urn:ocd:pg-book:native-inverse:" if item_id in PG_BOOK_ITEMS else
        "urn:ocd:paton:native-inverse:" if item_id.startswith("paton-missionary-") else
        "urn:ocd:pg49917:source-marker:" if item_id in PG49917_ITEMS else
        "urn:ocd:clement:source-marker:" if item_id in CLEMENT_ITEMS else None
    )
    if prefix is None or not value.startswith(prefix):
        raise PipelineError(f"{item_id}: unapproved PG source annotation")
    encoded = value.removeprefix(prefix)
    try:
        source = json.loads(unquote(encoded, errors="strict"), object_pairs_hook=_unique_pairs)
    except (ValueError, UnicodeError) as exc:
        raise PipelineError("invalid PG source annotation") from exc
    if quote(json.dumps(source, ensure_ascii=False, separators=(",", ":")), safe="") != encoded:
        raise PipelineError("noncanonical PG source annotation")
    if item_id in PG_BOOK_ITEMS or item_id.startswith("paton-missionary-"):
        if isinstance(source, list):
            if item_id == NOAH_ITEM and any(
                    isinstance(pair, list) and pair and pair[0] == "corresp"
                    for pair in source):
                public, _, _ = _pg_noah_image_pairs(source)
            else:
                public = _pg_pairs(source)
        elif (item_id in PG_BOOK_ITEMS and isinstance(source, dict)
              and source.get("tag") in {"add", "title", "milestone", "figure"}
              and set(source) in ({"tag", "attributes"},
                                  {"tag", "attributes", "children_attributes"})):
            public = {"tag": source["tag"], "attributes": _pg_pairs(source["attributes"])}
            if "children_attributes" in source:
                children = source["children_attributes"]
                if (source["tag"] != "figure" or not isinstance(children, list)
                        or len(children) != 1 or not isinstance(children[0], dict)
                        or set(children[0]) != {"position", "tag", "attributes"}
                        or children[0]["position"] != 1 or children[0]["tag"] != "figDesc"):
                    raise PipelineError("PG nested figure annotation differs")
                public["children_attributes"] = [{"position": 1, "tag": "figDesc",
                                                  "attributes": _pg_pairs(children[0]["attributes"])}]
        else:
            raise PipelineError("PG native inverse shape differs")
    elif (isinstance(source, dict) and set(source).issubset(
            {"unit", "n", _PG_XML_ID, "rend"})
          and {"unit", "n"}.issubset(source)
          and all(isinstance(part, str) for part in source.values())):
        public = {key: (_pg_strip_digest(value) if key == "rend" else value)
                  for key, value in source.items()}
        public = {key: value for key, value in public.items() if value is not None}
        if any(_scan(value, "PG source marker") for value in public.values()):
            raise PipelineError("private PG source marker cannot be public")
    else:
        raise PipelineError("PG source marker shape differs")
    result = "source-annotation:" + quote(
        json.dumps(public, ensure_ascii=False, separators=(",", ":")), safe="")
    if _scan(result, "PG public annotation"):
        raise PipelineError("private PG annotation remains after transformation")
    return result


def _pg_source_target(value: str, item_id: str, node: dict[str, Any],
                      original_attributes: dict[str, Any]) -> str:
    if node.get("kind") != "image-reference":
        raise PipelineError("PG private source target is not an image reference")
    if item_id in PG_BOOK_ITEMS and value.startswith("data:image/"):
        if not re.match(r"data:image/(?:jpeg|png|gif);base64,[A-Za-z0-9+/=]+\Z", value):
            raise PipelineError("unapproved PG-book embedded image target")
        original = original_attributes.get("source_annotations")
        if not isinstance(original, str) or not original.startswith("urn:ocd:pg-book:native-inverse:"):
            raise PipelineError("PG-book image lacks original source member")
        source = json.loads(unquote(original.removeprefix("urn:ocd:pg-book:native-inverse:")))
        pairs = source["attributes"] if isinstance(source, dict) else source
        if item_id == NOAH_ITEM:
            _, embedded, member = _pg_noah_image_pairs(pairs)
            if value != embedded:
                raise PipelineError("Noah Davis image target differs from source annotation")
            return "source-image:" + member
        members = [part for key, part in pairs if key == "url"]
        if not members and item_id == "william-derham-physico-theology-1720--pg75254-1720-london":
            members = [matched[1] for key, part in pairs if key == "rend"
                       for matched in re.finditer(
                           r"(?:^| )source-image-member:(images/[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|gif))(?= |$)",
                           part, re.I)]
        if len(members) != 1 or not _PG_IMAGE_MEMBER.fullmatch(members[0]):
            raise PipelineError("PG-book image source member differs")
        return "source-image:" + members[0]
    if item_id == "jarena-lee-religious-experience-and-journal--jarena-lee-religious-experience-and-journal-gutenberg-electronic":
        matched = _JARENA_IMAGE.fullmatch(value)
        if matched is None:
            raise PipelineError("unapproved Jarena image source path")
        return "source-image:" + matched[1]
    raise PipelineError(f"{item_id}: unapproved private image target")


def _pg_public_field(key: str, before: str, item_id: str,
                     node: dict[str, Any], original_attributes: dict[str, Any]) -> str | None:
    if key == "source_annotations":
        if item_id == SPURGEON_ITEM and before == SPURGEON_MARKER:
            if (node.get("kind") != "source-marker" or node.get("content") != []
                    or set(original_attributes) != {"number", "unit", "source_annotations"}
                    or original_attributes["unit"] != "source-text-break"
                    or not re.fullmatch(r"(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01])",
                                        original_attributes["number"])):
                raise PipelineError("Spurgeon day marker carrier differs")
        if item_id == TERESA_ITEM and before == TERESA_PRIVATE_ANNOTATION:
            children = node.get("content")
            if (node.get("kind") != "segment"
                    or set(original_attributes) != {"source_annotations", "number"}
                    or not isinstance(original_attributes["number"], str)
                    or not original_attributes["number"]
                    or _scan(original_attributes["number"], "Teresa abbreviation expansion")
                    or not isinstance(children, list) or len(children) != 1
                    or not isinstance(children[0], dict)
                    or children[0].get("kind") != "abbreviated-text"
                    or children[0].get("attributes") not in (
                        {}, {"language": "la"}, {"language": "es"}, {"language": "fr"})
                    or not isinstance(children[0].get("content"), list)
                    or not children[0]["content"]):
                raise PipelineError("Teresa abbreviation expansion carrier differs")
        if item_id == NEWMAN_ITEM and before == NEWMAN_GREEK_MARKER:
            if (node.get("kind") != "segment"
                    or set(original_attributes) != {"number", "source_annotations"}
                    or not isinstance(original_attributes["number"], str)
                    or not original_attributes["number"]
                    or _scan(original_attributes["number"], "Newman Greek transliteration")):
                raise PipelineError("Newman Greek transliteration carrier differs")
        if item_id == PG42957_ITEM and before == PG42957_ROW_REND:
            if node.get("kind") != "table-row":
                raise PipelineError("PG42957 row rendition is not on a table row")
            return None
        return _pg_annotation(before, item_id) if before.startswith("urn:ocd:") else before
    if key == "style":
        if item_id == SPURGEON_ITEM:
            return None if before in {"style:margin-bottom:0in", "style:font-variant:small-caps"} else before
        return _pg_strip_digest(before)
    if key == "source_target":
        if before.startswith("data:image/") or _private_local_path(before):
            return _pg_source_target(before, item_id, node, original_attributes)
        return before
    raise PipelineError(f"unapproved PG public field: {key}")


def _pg_rows(rows: list[dict[str, Any]], item_id: str,
             acceptance_sha256: str | None, master_sha256: str | None
             ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    authority = _pg_authority(item_id, acceptance_sha256, master_sha256)
    public = deepcopy(rows)
    omissions = []
    for index, row in enumerate(public):
        fields = []

        def change(path: list[str | int], attributes: dict, key: str,
                   after: str | None) -> None:
            before = attributes[key]
            if after == before:
                return
            fields.append({"path": path + [key], "private": before, "public": after})
            if after is None:
                del attributes[key]
            else:
                attributes[key] = after

        provenance = row.get("provenance")
        if isinstance(provenance, dict) and _private_local_path(provenance.get("source_location")):
            change(["provenance"], provenance, "source_location", None)

        def visit(value: Any, path: list[str | int]) -> None:
            if isinstance(value, list):
                for position, child in enumerate(value):
                    visit(child, path + [position])
            elif isinstance(value, dict):
                attributes = value.get("attributes")
                if "kind" in value and isinstance(attributes, dict) and isinstance(value.get("content"), list):
                    original = attributes.copy()
                    for key in ("source_annotations", "style", "source_target"):
                        if key in attributes:
                            before = attributes[key]
                            if not isinstance(before, str):
                                raise PipelineError("PG native public attribute must be a string")
                            after = _pg_public_field(key, before, item_id, value, original)
                            change(path + ["attributes"], attributes, key, after)
                for key, child in value.items():
                    if key != "attributes":
                        visit(child, path + [key])

        visit(row, [])
        if fields:
            omissions.append({"row_index": index, "record_id": row.get("record_id"),
                              "original_row_sha256": _digest(rows[index]),
                              "public_row_sha256": _digest(row), "fields": fields})
    if item_id == PG42957_ITEM:
        removed_row_renditions = sum(
            field["private"] == PG42957_ROW_REND
            for omission in omissions for field in omission["fields"]
            if field["path"][-2:] == ["attributes", "source_annotations"]
        )
        if removed_row_renditions != 1:
            raise PipelineError("PG42957 requires its one exact table-row rendition")
    if item_id == TERESA_ITEM:
        aliased = sum(
            field["private"] == TERESA_PRIVATE_ANNOTATION
            for omission in omissions for field in omission["fields"]
            if field["path"][-2:] == ["attributes", "source_annotations"]
        )
        if aliased != 528:
            raise PipelineError("Teresa requires its 528 abbreviation expansions")
    if item_id == NEWMAN_ITEM:
        greek_markers = sum(
            field["private"] == NEWMAN_GREEK_MARKER
            for omission in omissions for field in omission["fields"]
            if field["path"][-2:] == ["attributes", "source_annotations"]
        )
        if len(rows) != 11 or greek_markers != 26:
            raise PipelineError("Newman source units or Greek marker inventory differs")
    if item_id == SPURGEON_ITEM:
        counts = {key: 0 for key in (SPURGEON_MARKER, "style:margin-bottom:0in",
                                     "style:font-variant:small-caps")}
        for omission in omissions:
            for field in omission["fields"]:
                if field["private"] in counts:
                    counts[field["private"]] += 1
        if counts != {SPURGEON_MARKER: 369, "style:margin-bottom:0in": 732,
                      "style:font-variant:small-caps": 48}:
            raise PipelineError("Spurgeon source marker or presentation inventory differs")
    if not omissions:
        return public, None
    return public, {"contract": PG_CONTRACT, "item_id": item_id, "authority": authority,
                    "row_count": len(rows), "omissions": omissions}


def _restore_pg(rows: list[dict[str, Any]], artifact: dict[str, Any], item_id: str,
                acceptance_sha256: str | None, master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _pg_authority(item_id, acceptance_sha256, master_sha256)
    if (set(artifact) != {"contract", "item_id", "authority", "row_count", "omissions"}
            or artifact["contract"] != PG_CONTRACT or artifact["item_id"] != item_id
            or artifact["authority"] != authority or type(artifact["row_count"]) is not int
            or artifact["row_count"] != len(rows) or not isinstance(artifact["omissions"], list)
            or not artifact["omissions"]):
        raise PipelineError("PG public-row transform contract differs")
    restored = deepcopy(rows)
    previous = -1
    for entry in artifact["omissions"]:
        if (not isinstance(entry, dict)
                or set(entry) != {"row_index", "record_id", "original_row_sha256", "public_row_sha256", "fields"}
                or type(entry["row_index"]) is not int
                or not previous < entry["row_index"] < len(rows)
                or not isinstance(entry["fields"], list) or not entry["fields"]):
            raise PipelineError("PG public-row transform entry differs")
        index = entry["row_index"]
        previous = index
        row = restored[index]
        if entry["record_id"] != row.get("record_id") or entry["public_row_sha256"] != _digest(row):
            raise PipelineError("PG public-row binding differs")
        used = set()
        for field in entry["fields"]:
            if (not isinstance(field, dict) or set(field) != {"path", "private", "public"}
                    or not isinstance(field["path"], list) or not field["path"]
                    or any(type(part) not in {str, int} for part in field["path"])
                    or not isinstance(field["private"], str)):
                raise PipelineError("PG public-row field differs")
            path = field["path"]
            if tuple(path) in used:
                raise PipelineError("duplicate PG public-row field")
            used.add(tuple(path))
            holder: Any = row
            try:
                for part in path[:-1]:
                    holder = holder[part]
            except (KeyError, IndexError, TypeError) as exc:
                raise PipelineError("PG public-row field path differs") from exc
            key = path[-1]
            if not isinstance(holder, dict) or not isinstance(key, str):
                raise PipelineError("PG public-row field target differs")
            if path == ["provenance", "source_location"]:
                expected = None if _private_local_path(field["private"]) else field["private"]
            elif len(path) >= 2 and path[-2] == "attributes" and key in {
                    "source_annotations", "style", "source_target"}:
                node: Any = row
                for part in path[:-2]:
                    node = node[part]
                if not isinstance(node, dict) or not isinstance(node.get("content"), list):
                    raise PipelineError("PG native node differs")
                original_attributes = dict(node.get("attributes", {}))
                for candidate in entry["fields"]:
                    if candidate["path"][:-1] == path[:-1]:
                        original_attributes[candidate["path"][-1]] = candidate["private"]
                expected = _pg_public_field(key, field["private"], item_id, node, original_attributes)
            else:
                raise PipelineError("unapproved PG public-row field")
            if (field["public"] != expected
                    or (expected is None and key in holder)
                    or (expected is not None and holder.get(key) != expected)):
                raise PipelineError("PG public-row field binding differs")
            holder[key] = field["private"]
        if entry["original_row_sha256"] != _digest(row):
            raise PipelineError("restored PG row differs from private binding")
    expected_public, expected_artifact = _pg_rows(restored, item_id, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("PG public-row omissions are incomplete")
    return restored


def _spurgeon_reference() -> dict[str, Any]:
    target = "http://www.ccel.org/ccel/spurgeon/morneve.today.html"
    return {"normalization_attribute": "target",
            "normalization_status": "unsupported-explicit-target",
            "raw": target, "source_child_path": [0, 3, 4, 0], "target": target}


def _spurgeon_parent(row: dict[str, Any]) -> dict[str, Any]:
    try:
        work = row["structure"][0]
        front = work["content"][0]
        parent = front["content"][3]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Spurgeon front-matter source path differs") from exc
    if (work.get("kind") != "division" or work.get("attributes") != {"type": "work"}
            or front.get("kind") != "division"
            or front.get("attributes") != {"type": "thml-div1"}
            or parent.get("kind") != "division"
            or parent.get("attributes") != {"style": "class:Center", "type": "centered-front-matter"}
            or not isinstance(parent.get("content"), list)):
        raise PipelineError("Spurgeon front-matter source structure differs")
    return parent


def _spurgeon_private_row_matches(row: dict[str, Any]) -> bool:
    """Bind the accepted row and the release's exact selected license."""
    return (row.get("license") == SPURGEON_LICENSE
            and _digest({key: value for key, value in row.items() if key != "license"})
            == SPURGEON_PRIVATE_ROW_SHA256)


def _spurgeon_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                   master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _pg_authority(SPURGEON_ITEM, acceptance_sha256, master_sha256)
    if len(rows) != 1 or not _spurgeon_private_row_matches(rows[0]):
        raise PipelineError("Spurgeon accepted private row differs")
    from ocd_kernel.projection.native_content import readable_content

    intermediate = deepcopy(rows)
    row = intermediate[0]
    parent = _spurgeon_parent(row)
    if (len(parent["content"]) != 5
            or sha256(canonical_bytes(parent["content"][4])).hexdigest()
            != SPURGEON_PARAGRAPH_SHA256
            or not isinstance(row.get("source_references"), list)
            or len(row["source_references"]) <= 2
            or row["source_references"].count(_spurgeon_reference()) != 1
            or row["source_references"][2] != _spurgeon_reference()
            or row.get("text") != readable_content(row["structure"][0])):
        raise PipelineError("Spurgeon modern source paragraph or link differs")
    paragraph = parent["content"].pop(4)
    reference = row["source_references"].pop(2)
    row["text"] = readable_content(row["structure"][0])
    public, inner = _pg_rows(intermediate, SPURGEON_ITEM, acceptance_sha256, master_sha256)
    if inner is None or _scan(public, "Spurgeon public rows"):
        raise PipelineError("Spurgeon public rows retain private source content")
    return public, {"contract": SPURGEON_CONTRACT, "item_id": SPURGEON_ITEM,
                    "authority": authority, "private_row_sha256": _digest(rows[0]),
                    "public_row_sha256": _digest(public[0]),
                    "removed_paragraph": paragraph, "removed_reference": reference,
                    "inner": inner}


def _restore_spurgeon(rows: list[dict[str, Any]], artifact: dict[str, Any],
                      acceptance_sha256: str | None,
                      master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _pg_authority(SPURGEON_ITEM, acceptance_sha256, master_sha256)
    if (len(rows) != 1
            or set(artifact) != {"contract", "item_id", "authority", "private_row_sha256",
                                 "public_row_sha256", "removed_paragraph", "removed_reference", "inner"}
            or artifact["contract"] != SPURGEON_CONTRACT
            or artifact["item_id"] != SPURGEON_ITEM or artifact["authority"] != authority
            or not isinstance(artifact["private_row_sha256"], str)
            or artifact["public_row_sha256"] != _digest(rows[0])
            or not isinstance(artifact["removed_paragraph"], dict)
            or sha256(canonical_bytes(artifact["removed_paragraph"])).hexdigest()
            != SPURGEON_PARAGRAPH_SHA256
            or artifact["removed_reference"] != _spurgeon_reference()):
        raise PipelineError("Spurgeon public source-layer receipt differs")
    from ocd_kernel.projection.native_content import readable_content

    intermediate = _restore_pg(rows, artifact["inner"], SPURGEON_ITEM,
                               acceptance_sha256, master_sha256)
    restored = deepcopy(intermediate)
    row = restored[0]
    parent = _spurgeon_parent(row)
    if (len(parent["content"]) != 4 or row["text"] != readable_content(row["structure"][0])
            or len(row["source_references"]) < 2):
        raise PipelineError("Spurgeon public front-matter structure differs")
    parent["content"].insert(4, deepcopy(artifact["removed_paragraph"]))
    row["source_references"].insert(2, deepcopy(artifact["removed_reference"]))
    row["text"] = readable_content(row["structure"][0])
    if (not _spurgeon_private_row_matches(row)
            or _digest(row) != artifact["private_row_sha256"]):
        raise PipelineError("Spurgeon private row inverse differs")
    expected_public, expected_artifact = _spurgeon_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Spurgeon public source-layer omissions are incomplete")
    return restored

def _finney_authority(acceptance_sha256: str | None,
                      master_sha256: str | None) -> dict[str, str]:
    if (acceptance_sha256 != FINNEY_ACCEPTANCE_SHA256
            or master_sha256 != FINNEY_MASTER_SHA256):
        raise PipelineError("Finney accepted historical authority differs")
    return {"acceptance_sha256": FINNEY_ACCEPTANCE_SHA256,
            "master_sha256": FINNEY_MASTER_SHA256,
            "finney_scope_evidence_sha256": FINNEY_SCOPE_SHA256}


def _finney_sections(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any],
                                                     dict[str, Any]]:
    try:
        work = row["structure"][0]
        front = work["content"][0]
        main = work["content"][6]
        generated_index = work["content"][8]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Finney accepted source structure differs") from exc
    if (work.get("kind") != "division" or work.get("attributes") != {"type": "work"}
            or len(work.get("content", [])) != 10
            or any(node.get("kind") != "division" for node in (front, main, generated_index))
            or not isinstance(front.get("content"), list)
            or not isinstance(main.get("content"), list)
            or not isinstance(row.get("source_references"), list)
            or len(row["source_references"]) != 2105):
        raise PipelineError("Finney historical source sections differ")
    return work, front, main


def _finney_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                 master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _finney_authority(acceptance_sha256, master_sha256)
    if (len(rows) != 1 or rows[0].get("license") != FINNEY_LICENSE
            or _digest(rows[0]) != FINNEY_PRIVATE_ROW_SHA256):
        raise PipelineError("Finney selected accepted private row differs")
    from ocd_kernel.projection.native_content import readable_content

    public = deepcopy(rows)
    row = public[0]
    work, front, main = _finney_sections(row)
    if (len(front["content"]) != 33 or len(main["content"]) != 107
            or _digest(front["content"][19:]) != FINNEY_FRONT_TAIL_SHA256
            or _digest(main["content"][105:]) != FINNEY_MAIN_TAIL_SHA256
            or row.get("text") != readable_content(work)):
        raise PipelineError("Finney modern publisher layer differs")
    front_tail = front["content"][19:]
    main_tail = main["content"][105:]
    del front["content"][19:]
    del main["content"][105:]
    row["text"] = readable_content(work)
    if _digest(row) != FINNEY_PUBLIC_ROW_SHA256 or _scan(public, "Finney historical public row"):
        raise PipelineError("Finney historical public row differs")
    return public, {"contract": FINNEY_CONTRACT, "item_id": FINNEY_ITEM,
                    "authority": authority, "private_row_sha256": FINNEY_PRIVATE_ROW_SHA256,
                    "public_row_sha256": FINNEY_PUBLIC_ROW_SHA256,
                    "removed_front_tail": front_tail, "removed_main_tail": main_tail}


def _restore_finney(rows: list[dict[str, Any]], artifact: dict[str, Any],
                    acceptance_sha256: str | None, master_sha256: str | None) -> list[dict[str, Any]]:
    authority = _finney_authority(acceptance_sha256, master_sha256)
    if (len(rows) != 1 or not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "authority", "private_row_sha256",
                                 "public_row_sha256", "removed_front_tail", "removed_main_tail"}
            or artifact["contract"] != FINNEY_CONTRACT or artifact["item_id"] != FINNEY_ITEM
            or artifact["authority"] != authority
            or artifact["private_row_sha256"] != FINNEY_PRIVATE_ROW_SHA256
            or artifact["public_row_sha256"] != FINNEY_PUBLIC_ROW_SHA256
            or _digest(rows[0]) != FINNEY_PUBLIC_ROW_SHA256
            or not isinstance(artifact["removed_front_tail"], list)
            or len(artifact["removed_front_tail"]) != 14
            or _digest(artifact["removed_front_tail"]) != FINNEY_FRONT_TAIL_SHA256
            or not isinstance(artifact["removed_main_tail"], list)
            or len(artifact["removed_main_tail"]) != 2
            or _digest(artifact["removed_main_tail"]) != FINNEY_MAIN_TAIL_SHA256):
        raise PipelineError("Finney private publisher-layer receipt differs")
    from ocd_kernel.projection.native_content import readable_content

    restored = deepcopy(rows)
    row = restored[0]
    work, front, main = _finney_sections(row)
    if (len(front["content"]) != 19 or len(main["content"]) != 105
            or row.get("text") != readable_content(work)):
        raise PipelineError("Finney public section shape differs")
    front["content"].extend(deepcopy(artifact["removed_front_tail"]))
    main["content"].extend(deepcopy(artifact["removed_main_tail"]))
    row["text"] = readable_content(work)
    if _digest(row) != FINNEY_PRIVATE_ROW_SHA256:
        raise PipelineError("Finney accepted private inverse differs")
    expected_public, expected_artifact = _finney_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Finney public publisher-layer omissions are incomplete")
    return restored

def _charnock_ledger_matches(node: object, *, count: int, digest: str) -> bool:
    """Recognize only an exact retained source-line bookkeeping division."""
    return (isinstance(node, dict)
            and node.get("attributes") == {
                "type": "complete-xml-node-transcription",
                "subtype": "source-line-accountability"}
            and len(node.get("content", [])) == count
            and _digest(node) == digest)


def _charnock_authority(acceptance_sha256: str | None,
                        master_sha256: str | None) -> dict[str, str]:
    if ((acceptance_sha256, master_sha256)
            != (CHARNOCK_ACCEPTANCE_SHA256, CHARNOCK_MASTER_SHA256)):
        raise PipelineError("Charnock volume I accepted authority differs")
    return {"acceptance_sha256": CHARNOCK_ACCEPTANCE_SHA256,
            "master_sha256": CHARNOCK_MASTER_SHA256,
            "charnock_scope_evidence_sha256": CHARNOCK_SCOPE_SHA256}


def _charnock_parts(rows: list[dict[str, Any]], *, public: bool
                    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        volume = rows[0]["structure"][0]
        shared = rows[1]["structure"][0]
        front = volume["content"][0]["content"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Charnock volume I source structure differs") from exc
    if (len(rows) != 2
            or any(row.get("license") != CHARNOCK_LICENSE for row in rows)
            or [len(row.get("source_references", [])) for row in rows] != [809, 0]
            or any(len(row.get("structure", [])) != 1 for row in rows)
            or volume.get("kind") != "division"
            or volume.get("attributes") != {"type": "volume-body", "number": "1"}
            or shared.get("kind") != "division"
            or shared.get("attributes") != {"type": "shared-apparatus"}
            or front.get("kind") != "division"
            or front.get("attributes") != {"type": "front-matter"}
            or len(volume.get("content", [])) != (1 if public else 2)
            or len(shared.get("content", [])) != (2 if public else 3)
            or len(front.get("content", [])) != (284 if public else 286)):
        raise PipelineError("Charnock volume I selected sections differ")
    return volume, shared, front


def _charnock_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                   master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _charnock_authority(acceptance_sha256, master_sha256)
    if _digest(rows) != CHARNOCK_PRIVATE_ROWS_SHA256:
        raise PipelineError("Charnock volume I licensed private rows differ")
    volume, shared, front = _charnock_parts(rows, public=False)
    from ocd_kernel.projection.native_content import readable_content

    if (any(row["text"] != readable_content(row["structure"][0]) for row in rows)
            or not _charnock_ledger_matches(volume["content"][1], count=30275,
                                            digest=CHARNOCK_VOLUME_LEDGER_SHA256)
            or not _charnock_ledger_matches(shared["content"][2], count=6013,
                                            digest=CHARNOCK_SHARED_LEDGER_SHA256)
            or _digest(front["content"][45:47]) != CHARNOCK_PROMOTION_SHA256):
        raise PipelineError("Charnock private source ledger or Baker promotion differs")
    public_rows = deepcopy(rows)
    public_volume, public_shared, public_front = _charnock_parts(public_rows, public=False)
    removed_volume_ledger = public_volume["content"].pop(1)
    removed_shared_ledger = public_shared["content"].pop(2)
    removed_promotion = public_front["content"][45:47]
    del public_front["content"][45:47]
    public_rows[0]["text"] = readable_content(public_volume)
    if (public_rows[1]["text"] != readable_content(public_shared)
            or _digest(public_rows) != CHARNOCK_PUBLIC_ROWS_SHA256
            or _scan(public_rows, "Charnock volume I public rows")):
        raise PipelineError("Charnock volume I public source boundary differs")
    return public_rows, {
        "contract": CHARNOCK_CONTRACT, "item_id": CHARNOCK_ITEM,
        "authority": authority,
        "private_rows_sha256": CHARNOCK_PRIVATE_ROWS_SHA256,
        "public_rows_sha256": CHARNOCK_PUBLIC_ROWS_SHA256,
        "removed_volume_ledger": removed_volume_ledger,
        "removed_shared_ledger": removed_shared_ledger,
        "removed_promotion": removed_promotion,
    }


def _restore_charnock(rows: list[dict[str, Any]], artifact: dict[str, Any],
                      acceptance_sha256: str | None, master_sha256: str | None
                      ) -> list[dict[str, Any]]:
    authority = _charnock_authority(acceptance_sha256, master_sha256)
    if (set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                          "public_rows_sha256", "removed_volume_ledger",
                          "removed_shared_ledger", "removed_promotion"}
            or artifact["contract"] != CHARNOCK_CONTRACT
            or artifact["item_id"] != CHARNOCK_ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != CHARNOCK_PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != CHARNOCK_PUBLIC_ROWS_SHA256
            or _digest(rows) != CHARNOCK_PUBLIC_ROWS_SHA256
            or not _charnock_ledger_matches(artifact["removed_volume_ledger"], count=30275,
                                            digest=CHARNOCK_VOLUME_LEDGER_SHA256)
            or not _charnock_ledger_matches(artifact["removed_shared_ledger"], count=6013,
                                            digest=CHARNOCK_SHARED_LEDGER_SHA256)
            or not isinstance(artifact["removed_promotion"], list)
            or _digest(artifact["removed_promotion"]) != CHARNOCK_PROMOTION_SHA256):
        raise PipelineError("Charnock volume I private source-ledger receipt differs")
    from ocd_kernel.projection.native_content import readable_content

    restored = deepcopy(rows)
    volume, shared, front = _charnock_parts(restored, public=True)
    if (any(row["text"] != readable_content(row["structure"][0]) for row in rows)
            or _scan(rows, "Charnock volume I public rows")):
        raise PipelineError("Charnock volume I public rows differ")
    front["content"][45:45] = deepcopy(artifact["removed_promotion"])
    volume["content"].append(deepcopy(artifact["removed_volume_ledger"]))
    shared["content"].append(deepcopy(artifact["removed_shared_ledger"]))
    restored[0]["text"] = readable_content(volume)
    if _digest(restored) != CHARNOCK_PRIVATE_ROWS_SHA256:
        raise PipelineError("Charnock volume I accepted private inverse differs")
    expected_public, expected_artifact = _charnock_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Charnock volume I public omissions are incomplete")
    return restored


def _charnock_v2_authority(acceptance_sha256: str | None,
                          master_sha256: str | None) -> dict[str, str]:
    if ((acceptance_sha256, master_sha256)
            != (CHARNOCK_V2_ACCEPTANCE_SHA256, CHARNOCK_V2_MASTER_SHA256)):
        raise PipelineError("Charnock volume II accepted authority differs")
    return {"acceptance_sha256": CHARNOCK_V2_ACCEPTANCE_SHA256,
            "master_sha256": CHARNOCK_V2_MASTER_SHA256,
            "charnock_scope_evidence_sha256": CHARNOCK_V2_SCOPE_SHA256}


def _charnock_v2_parts(rows: list[dict[str, Any]], *, public: bool
                       ) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        volume = rows[0]["structure"][0]
        shared = rows[1]["structure"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError("Charnock volume II source structure differs") from exc
    if (len(rows) != 2
            or any(row.get("license") != CHARNOCK_V2_LICENSE for row in rows)
            or [len(row.get("source_references", [])) for row in rows] != [234, 0]
            or any(len(row.get("structure", [])) != 1 for row in rows)
            or volume.get("kind") != "division"
            or volume.get("attributes") != {"type": "volume-body", "number": "2"}
            or shared.get("kind") != "division"
            or shared.get("attributes") != {"type": "shared-apparatus"}
            or len(volume.get("content", [])) != (1 if public else 2)
            or len(shared.get("content", [])) != (2 if public else 3)):
        raise PipelineError("Charnock volume II selected sections differ")
    return volume, shared


def _charnock_v2_rows(rows: list[dict[str, Any]], acceptance_sha256: str | None,
                      master_sha256: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    authority = _charnock_v2_authority(acceptance_sha256, master_sha256)
    if _digest(rows) != CHARNOCK_V2_PRIVATE_ROWS_SHA256:
        raise PipelineError("Charnock volume II licensed private rows differ")
    volume, shared = _charnock_v2_parts(rows, public=False)
    from ocd_kernel.projection.native_content import readable_content

    if (any(row["text"] != readable_content(row["structure"][0]) for row in rows)
            or not _charnock_ledger_matches(volume["content"][1], count=26127,
                                            digest=CHARNOCK_V2_VOLUME_LEDGER_SHA256)
            or not _charnock_ledger_matches(shared["content"][2], count=6013,
                                            digest=CHARNOCK_V2_SHARED_LEDGER_SHA256)):
        raise PipelineError("Charnock volume II private source ledgers differ")
    public_rows = deepcopy(rows)
    public_volume, public_shared = _charnock_v2_parts(public_rows, public=False)
    removed_volume_ledger = public_volume["content"].pop(1)
    removed_shared_ledger = public_shared["content"].pop(2)
    if (any(public_row["text"] != private_row["text"]
            or public_row["text"] != readable_content(public_row["structure"][0])
            or public_row["source_references"] != private_row["source_references"]
            for public_row, private_row in zip(public_rows, rows, strict=True))
            or _digest(public_rows) != CHARNOCK_V2_PUBLIC_ROWS_SHA256
            or _scan(public_rows, "Charnock volume II public rows")):
        raise PipelineError("Charnock volume II public source boundary differs")
    return public_rows, {
        "contract": CHARNOCK_V2_CONTRACT, "item_id": CHARNOCK_V2_ITEM,
        "authority": authority,
        "private_rows_sha256": CHARNOCK_V2_PRIVATE_ROWS_SHA256,
        "public_rows_sha256": CHARNOCK_V2_PUBLIC_ROWS_SHA256,
        "removed_volume_ledger": removed_volume_ledger,
        "removed_shared_ledger": removed_shared_ledger,
    }


def _restore_charnock_v2(rows: list[dict[str, Any]], artifact: dict[str, Any],
                         acceptance_sha256: str | None, master_sha256: str | None
                         ) -> list[dict[str, Any]]:
    authority = _charnock_v2_authority(acceptance_sha256, master_sha256)
    if (set(artifact) != {"contract", "item_id", "authority", "private_rows_sha256",
                          "public_rows_sha256", "removed_volume_ledger",
                          "removed_shared_ledger"}
            or artifact["contract"] != CHARNOCK_V2_CONTRACT
            or artifact["item_id"] != CHARNOCK_V2_ITEM
            or artifact["authority"] != authority
            or artifact["private_rows_sha256"] != CHARNOCK_V2_PRIVATE_ROWS_SHA256
            or artifact["public_rows_sha256"] != CHARNOCK_V2_PUBLIC_ROWS_SHA256
            or _digest(rows) != CHARNOCK_V2_PUBLIC_ROWS_SHA256
            or not _charnock_ledger_matches(artifact["removed_volume_ledger"], count=26127,
                                            digest=CHARNOCK_V2_VOLUME_LEDGER_SHA256)
            or not _charnock_ledger_matches(artifact["removed_shared_ledger"], count=6013,
                                            digest=CHARNOCK_V2_SHARED_LEDGER_SHA256)):
        raise PipelineError("Charnock volume II private source-ledger receipt differs")
    from ocd_kernel.projection.native_content import readable_content

    restored = deepcopy(rows)
    volume, shared = _charnock_v2_parts(restored, public=True)
    if (any(row["text"] != readable_content(row["structure"][0]) for row in rows)
            or _scan(rows, "Charnock volume II public rows")):
        raise PipelineError("Charnock volume II public rows differ")
    volume["content"].append(deepcopy(artifact["removed_volume_ledger"]))
    shared["content"].append(deepcopy(artifact["removed_shared_ledger"]))
    if _digest(restored) != CHARNOCK_V2_PRIVATE_ROWS_SHA256:
        raise PipelineError("Charnock volume II accepted private inverse differs")
    expected_public, expected_artifact = _charnock_v2_rows(
        restored, acceptance_sha256, master_sha256)
    if expected_public != rows or expected_artifact != artifact:
        raise PipelineError("Charnock volume II public omissions are incomplete")
    return restored
