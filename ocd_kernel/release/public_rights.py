"""Exact reversible license and public-scope amendments for the first release.

Only the pinned new label for each item enters this wrapper. Old selections use
their original public-row route unchanged. The inner transform and its private
inverse are replayed without weakening their historical row checks.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from ocd_kernel.library._common import PipelineError, canonical_bytes


CONTRACT = "ocd-publication-rights-17-reversible-v1"
CANDIDATE_SHA256 = "c15dd75e8e96e7dee725b13f1698b1cd16b40acf7c1ff78457618c5a378c9fb1"
EDWARDS_ITEM = "edwards-select-sermons--edwards-select-sermons-ccel-thml-electronic"
EDWARDS_RETAINED = tuple(range(1, 20))
EDWARDS_OMITTED = (0, 20)

# Original entries came from the reviewed rights candidate and read-only 17-item
# baseline inventory. Current public labels also follow reviewed U.S. normalization.
# Each entry pins source authority and old row scope.
SPECS: dict[str, dict[str, Any]] = {
    'bounds-power-through-prayer--bounds-power-through-prayer-ccel-thml-electronic': {
        'acceptance_path': 'library/works/bounds-power-through-prayer/forms/bounds-power-through-prayer-english/editions/bounds-power-through-prayer-ccel-thml-electronic/acceptance.json',
        'acceptance_sha256': '3e882bb5beccab01973daef0e660d6e18faa6b77d2996659748e91b52d1e676c',
        'baseline_row_count': 1,
        'edition_id': 'bounds-power-through-prayer-ccel-thml-electronic',
        'license_after': 'Public domain (United States): identified historical E. M. Bounds text and quotations; extracted text sourced via CCEL.org; reserved CCEL files and formatting excluded',
        'license_before': 'Public domain (United States) for identified historical text; CCEL electronic source used with retained text-use permission for private offline preparation',
        'master_path': 'library/works/bounds-power-through-prayer/forms/bounds-power-through-prayer-english/editions/bounds-power-through-prayer-ccel-thml-electronic/master.tei.xml',
        'master_sha256': '9e3b3b2da1e5fc8d5b3729bb7534795b13fa1e138410646c65d927de76aa87bc',
        'old_private_rows_sha256': '062aa16c3969c6a8d7c4b85444867c73a8057ebbcd7c650e1d8da48069b82731',
        'old_public_rows_sha256': '0015e2cb1c644cd1e6d448983857508c645829b5c44a6b2f92ca36a978917bd6',
        'old_transform_sha256': '1733ec0fe78ae48db93243bf9f7a466c355178be8515a4ea35a441b032df04e3',
        'public_row_count': 1,
        'work_id': 'bounds-power-through-prayer',
    },
    'bounds-weapon-of-prayer--bounds-weapon-of-prayer-ccel-thml-electronic': {
        'acceptance_path': 'library/works/bounds-weapon-of-prayer/forms/bounds-weapon-of-prayer-english/editions/bounds-weapon-of-prayer-ccel-thml-electronic/acceptance.json',
        'acceptance_sha256': '8cfe56578ca122df461e398daa020ccee90ae40dff8b1b79b4c415f83a9041a1',
        'baseline_row_count': 1,
        'edition_id': 'bounds-weapon-of-prayer-ccel-thml-electronic',
        'license_after': 'public-domain',
        'license_before': 'Retained CCEL source states Public Domain for this text; private text use under CCEL permission, with file and formatting rights reserved',
        'master_path': 'library/works/bounds-weapon-of-prayer/forms/bounds-weapon-of-prayer-english/editions/bounds-weapon-of-prayer-ccel-thml-electronic/master.tei.xml',
        'master_sha256': '1cb44da0dd359cc1da0c5a7ce6b1cb2d4a472de682bd9da8313b59414d7266bb',
        'old_private_rows_sha256': '390a342145c009446791ed90fa14315ca70ae8c9dfffb27a194a9b3717d58b6f',
        'old_public_rows_sha256': '390a342145c009446791ed90fa14315ca70ae8c9dfffb27a194a9b3717d58b6f',
        'old_transform_sha256': None,
        'public_row_count': 1,
        'work_id': 'bounds-weapon-of-prayer',
    },
    'bunyan-grace-abounding--bunyan-grace-abounding-ccel-thml-electronic': {
        'acceptance_path': 'library/works/bunyan-grace-abounding/forms/bunyan-grace-abounding-english/editions/bunyan-grace-abounding-ccel-thml-electronic/acceptance.json',
        'acceptance_sha256': '202965204aa31132d3443577e794d97ebf76aa0064dfd385867057654342eea8',
        'baseline_row_count': 1,
        'edition_id': 'bunyan-grace-abounding-ccel-thml-electronic',
        'license_after': 'Public domain (United States): identified 1666 John Bunyan text and factual scripture index; later publisher foreword and CCEL files/formatting excluded',
        'license_before': 'Public domain (United States) for identified 1666 Bunyan historical text and factual scripture index; CCEL electronic source used with retained text-use permission for private offline preparation',
        'master_path': 'library/works/bunyan-grace-abounding/forms/bunyan-grace-abounding-english/editions/bunyan-grace-abounding-ccel-thml-electronic/master.tei.xml',
        'master_sha256': '8da7b1534bd8ef88fe6c2e15dc5496e9d0f0d4d1906265fc311418b44eb0e607',
        'old_private_rows_sha256': 'fe4a3a5da0512b6234fbadfcd9271384f063e26d1d9b0156c51c870d190a09d1',
        'old_public_rows_sha256': '16148f13c700f064b34d9e74c106485aaf530ce623d3616b415434a1a3fbccca',
        'old_transform_sha256': '49ca705e0bfb81f7410c3037b203046c7a5d79fdfdb684cc399fb40effc9241e',
        'public_row_count': 1,
        'work_id': 'bunyan-grace-abounding',
    },
    'edwards-select-sermons--edwards-select-sermons-ccel-thml-electronic': {
        'acceptance_path': 'library/works/edwards-select-sermons/forms/edwards-select-sermons-english/editions/edwards-select-sermons-ccel-thml-electronic/acceptance.json',
        'acceptance_sha256': '9e5aa76554b253bdf7d09b2825d2c8f0827f35e2da2fd6c17a1c6bbae5ee9b26',
        'baseline_row_count': 21,
        'edition_id': 'edwards-select-sermons-ccel-thml-electronic',
        'license_after': 'Public domain (United States): nineteen identified historical Jonathan Edwards sermons and historical paratext; CCEL collection title/contents, electronic indexes, contributor outline and formatting excluded',
        'license_before': "Public domain (United States) for Jonathan Edwards's historical sermon text; CCEL electronic collection and factual indexes used under private educational text-use terms",
        'master_path': 'library/works/edwards-select-sermons/forms/edwards-select-sermons-english/editions/edwards-select-sermons-ccel-thml-electronic/master.tei.xml',
        'master_sha256': '10c21eab6f603b07b0116e5666d5d38f6383912b3806d5ab16ee433a7847bc92',
        'old_private_rows_sha256': 'f5f047f43315c441343e74e615efa33051176a5c9c17596467b9725e3335402b',
        'old_public_row_sha256': [
            '0a4c0bd5cf7e6ab0520bc8f286801bb92011b76a9a697f60d58a5a263997eb63',
            'ab59be7f19fc44c0caf36eb968a1707b8bb6aca07e3152893171ab15d11ee3e6',
            'f9f5d0997b4ad29a8e69b5caadbfc50bcf889782acfca226684479d4ec9885c5',
            '3afd7deb340bfa005530571350db4db630ea0b2d0c87869dbd4680536ea92008',
            '932b1da597e27a156a64b2fb6e506bb2e3b51b7bec38eacb08f758a702b46458',
            '17c40c320b7ce2539715ef45935e0f0596a442b457dafab69902f82fe871d9bd',
            '05216e0d5bc936dd14c5705612424398fd9833602c1d6c7f82b9eb1987b6c1af',
            '268d298160ed5adaf9fb60978fc44733cca12228155b847ad61fa1f21709af6a',
            '10db5e273c56748ca8b3552976492799e7548d4d0efea165d11b8311ed3fa28a',
            'accd2ea775d180fa3c6a3de3c87248f39ddc50e86922066ed20375c570d7349e',
            '30717905da5ebdc17ab211e4a69defcf227fc7f67864781a33f8a2216e5f28e0',
            '7a803bfb14cf93d34d2f9230323e5f8c90710b8c17697ad5ae577970db52bad1',
            'e0727c8e798d07eac3373d38d8625f4f2684c5d63e66cf6e30daf6311c406150',
            '4e9b18fb0e75b359f597b760b647d88e0d27891e5421d911882efffc3d5744c4',
            'd9a2bd26c228c4b1b0c24581eb98c589b7eaafbf12d72cfb4022a4b85b236a14',
            'e0f20b88ebcc78a58c6fb67d53b2a88a1b586ef55458bde43031f4a94a0f7802',
            '10c63c2d9e465d95b3db7cb9e4176210c70c1623c86437b37546fb240164a79e',
            'c15206a7004bbba7d981e4b7658f12ec3cdb046dac70d6d0b53aa63cd0d4f27f',
            '441f232110a46e82f258a2031501ecf6ec1f05d06c53b48b867be7827a01404b',
            'dcb4e481f15f7432cf88cac8a1816a40b765fa3d9735d232f8190b17bbae07bc',
            'd8a21e47f7a7eec49e7260fedf40a8e5d81d1f9ffab9307becfd581086d59212',
        ],
        'old_public_rows_sha256': '2f9eb1fa2942e9785a86c8dbb83b6fd5782e51328c8088aa56a8e64a284e5092',
        'old_transform_sha256': '68cb0074a690fa42ef3f32facbf1f75421892586971f75ecad756db163da720d',
        'public_row_count': 19,
        'record_ids': [
            'edwards-select-sermons-ccel-thml-electronic:native:df13288550fb06f3eda9',
            'edwards-select-sermons-ccel-thml-electronic:native:7c54d73c4aa0239d6b87',
            'edwards-select-sermons-ccel-thml-electronic:native:66269ad98c35763a1894',
            'edwards-select-sermons-ccel-thml-electronic:native:80e075a9078e6493a20c',
            'edwards-select-sermons-ccel-thml-electronic:native:29fc603679ee31a722bc',
            'edwards-select-sermons-ccel-thml-electronic:native:8bfecb2e89c60bc38d56',
            'edwards-select-sermons-ccel-thml-electronic:native:c9e89088f007f2ccd3e7',
            'edwards-select-sermons-ccel-thml-electronic:native:282490fedf754449b7f0',
            'edwards-select-sermons-ccel-thml-electronic:native:4a3afa0e6349f0cb623b',
            'edwards-select-sermons-ccel-thml-electronic:native:4419c2cf1c11190d1249',
            'edwards-select-sermons-ccel-thml-electronic:native:0f80b39db2d184c18ec3',
            'edwards-select-sermons-ccel-thml-electronic:native:cce30688de442d0362e2',
            'edwards-select-sermons-ccel-thml-electronic:native:843b0c6293940e732e0e',
            'edwards-select-sermons-ccel-thml-electronic:native:7102d60b3f33f110f869',
            'edwards-select-sermons-ccel-thml-electronic:native:aff51774fe9a3a881ef6',
            'edwards-select-sermons-ccel-thml-electronic:native:74f854b278e700215420',
            'edwards-select-sermons-ccel-thml-electronic:native:679d92819f0a7d64b4bd',
            'edwards-select-sermons-ccel-thml-electronic:native:e5687e6060bfdcde7006',
            'edwards-select-sermons-ccel-thml-electronic:native:55e60ed56cb19474a95c',
            'edwards-select-sermons-ccel-thml-electronic:native:988fdd4e34832bbb13d1',
            'edwards-select-sermons-ccel-thml-electronic:native:6905b2ccf6faa58ed736',
        ],
        'work_id': 'edwards-select-sermons',
    },
    'george-whitefield-sermons--george-whitefield-sermons-ccel-retained-electronic': {
        'acceptance_path': 'library/works/george-whitefield-sermons/forms/george-whitefield-sermons-ccel-retained-en/editions/george-whitefield-sermons-ccel-retained-electronic/acceptance.json',
        'acceptance_sha256': 'ef6f7177552ef9b11038ff1d4c0afbf16aff1d223588f271f49d56648afa1428',
        'baseline_row_count': 59,
        'edition_id': 'george-whitefield-sermons-ccel-retained-electronic',
        'license_after': 'public-domain',
        'license_before': 'Retained CCEL source declares Public Domain for Whitefield sermon text; private underlying-text preparation with CCEL file and formatting rights reserved',
        'master_path': 'library/works/george-whitefield-sermons/forms/george-whitefield-sermons-ccel-retained-en/editions/george-whitefield-sermons-ccel-retained-electronic/master.tei.xml',
        'master_sha256': 'ccff41cdb4fca4c5968dd0b738c9d6a41218718aeed6296f6c4cd4c3a82a73e1',
        'old_private_rows_sha256': '7e73899a6cb93c0f3c225e6138094c230220259064d6c2846229c4b19743c080',
        'old_public_rows_sha256': '7e73899a6cb93c0f3c225e6138094c230220259064d6c2846229c4b19743c080',
        'old_transform_sha256': None,
        'public_row_count': 59,
        'work_id': 'george-whitefield-sermons',
    },
    'john-wesley-sermons--john-wesley-sermons-retained-electronic-edition': {
        'acceptance_path': 'library/works/john-wesley-sermons/forms/john-wesley-sermons-retained-electronic-en/editions/john-wesley-sermons-retained-electronic-edition/acceptance.json',
        'acceptance_sha256': 'c46dc1695bf12565415c3b359c36929e703ab684bec87376e1110fee0ef269c4',
        'baseline_row_count': 10,
        'edition_id': 'john-wesley-sermons-retained-electronic-edition',
        'license_after': 'Public domain (United States): identified historical Wesley sermon text and historical apparatus; extracted text sourced via CCEL.org; electronic files and formatting excluded',
        'license_before': 'Public domain (United States) for identified historical sermon text and apparatus; CCEL electronic source used with retained private text-use permission',
        'master_path': 'library/works/john-wesley-sermons/forms/john-wesley-sermons-retained-electronic-en/editions/john-wesley-sermons-retained-electronic-edition/master.tei.xml',
        'master_sha256': 'ba1e808e23b49fb623c8d0758731931b560a510aa42587666cf48079a35c5c1e',
        'old_private_rows_sha256': '0517318f48150fbec187ef399a0a105429953af854ee94986094accee07d8ee3',
        'old_public_rows_sha256': '0517318f48150fbec187ef399a0a105429953af854ee94986094accee07d8ee3',
        'old_transform_sha256': None,
        'public_row_count': 10,
        'work_id': 'john-wesley-sermons',
    },
    'kjva--kjva-retained-electronic-witness': {
        'acceptance_path': 'library/works/kjva/forms/kjva-english/editions/kjva-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': 'aa7b7f4f31a716cf8bcd0c5afc7fd1072916a44f019df4d702391b1e7a5d2609',
        'baseline_row_count': 36819,
        'edition_id': 'kjva-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical KJV wording; GPL-3.0 for any protectable electronic contribution (provider GPL without version, recipient elects GPLv3)',
        'license_before': 'Public domain (United States) for identified historical KJV wording; provider-labeled GPL electronic KJVA contribution under elected GNU GPLv3; private offline preparation',
        'master_path': 'library/works/kjva/forms/kjva-english/editions/kjva-retained-electronic-witness/master.tei.xml',
        'master_sha256': '0dcc49d942166bdf27072c4fb7df585731535f3e547e49c50c566858fb92fc21',
        'old_private_rows_sha256': '8600a178a52cb709f9b7cf3006130831a97fa496bf3e43d9093d8fe2996eb4cf',
        'old_public_rows_sha256': '8600a178a52cb709f9b7cf3006130831a97fa496bf3e43d9093d8fe2996eb4cf',
        'old_transform_sha256': None,
        'public_row_count': 36819,
        'work_id': 'kjva',
    },
    'murray-absolute-surrender--murray-absolute-surrender-retained-electronic-witness': {
        'acceptance_path': 'library/works/murray-absolute-surrender/forms/murray-absolute-surrender-english/editions/murray-absolute-surrender-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': 'b567a025666e263d3be4e5977337a2868465e616d07ffdd6937a839ad2dfddba',
        'baseline_row_count': 11,
        'edition_id': 'murray-absolute-surrender-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical Andrew Murray text; provider-designated Public Domain Claude King electronic transcription, with factual scripture references; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States) for identified Andrew Murray 1895 text; CCEL electronic witness under personal, educational, or nonprofit use terms for private offline preparation',
        'master_path': 'library/works/murray-absolute-surrender/forms/murray-absolute-surrender-english/editions/murray-absolute-surrender-retained-electronic-witness/master.tei.xml',
        'master_sha256': '35859aa63e43bdf2d341f37ec341d504f614f577237d8cb6b80d7dd22a581f6e',
        'old_private_rows_sha256': 'c88a524b24d1579c822309f479afac2f9f432eba6d9252b1dfbb13f016df613b',
        'old_public_rows_sha256': 'c88a524b24d1579c822309f479afac2f9f432eba6d9252b1dfbb13f016df613b',
        'old_transform_sha256': None,
        'public_row_count': 11,
        'work_id': 'murray-absolute-surrender',
    },
    'schaff-history-vol-1--schaff-history-vol-1-retained-electronic-witness': {
        'acceptance_path': 'library/works/schaff-history-vol-1/forms/schaff-history-vol-1-retained-electronic/editions/schaff-history-vol-1-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': 'ff3529f8e60d1bfa6b56dee09a668b4151c241e0168cd459187465f11634b058',
        'baseline_row_count': 2,
        'edition_id': 'schaff-history-vol-1-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical Philip Schaff volume 1 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Retained CCEL source declares Public Domain for Schaff volume I text; private preparation of the 1910-collated witness under CCEL text permission, with electronic file and formatting restrictions',
        'master_path': 'library/works/schaff-history-vol-1/forms/schaff-history-vol-1-retained-electronic/editions/schaff-history-vol-1-retained-electronic-witness/master.tei.xml',
        'master_sha256': '53efec33e90bb67578c93b17be86ed5f531bc7c85614542bc6dec5a5e674c59a',
        'old_private_rows_sha256': 'b3c73786b14b43011661dd766e1f0ef3e920cf0cc8e3fdb34c1f7cb4c9d73434',
        'old_public_rows_sha256': 'b3c73786b14b43011661dd766e1f0ef3e920cf0cc8e3fdb34c1f7cb4c9d73434',
        'old_transform_sha256': None,
        'public_row_count': 2,
        'work_id': 'schaff-history-vol-1',
    },
    'schaff-history-vol-2--schaff-history-vol-2-retained-electronic-witness': {
        'acceptance_path': 'library/works/schaff-history-vol-2/forms/schaff-history-vol-2-retained-electronic/editions/schaff-history-vol-2-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': '81d5512a0243018a28009a631e04c088fba401bd874694ebb1f5e4c8a03bb021',
        'baseline_row_count': 6,
        'edition_id': 'schaff-history-vol-2-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical Philip Schaff volume 2 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States): historical Philip Schaff volume 2 text; private CCEL electronic witness preparation, source-described 1910 Scribner edition, with reserved file and formatting rights',
        'master_path': 'library/works/schaff-history-vol-2/forms/schaff-history-vol-2-retained-electronic/editions/schaff-history-vol-2-retained-electronic-witness/master.tei.xml',
        'master_sha256': '039a944cf23d1d7384bf5f9fcefea0c203d6ce0174a1d51726dce2a4e6e668ea',
        'old_private_rows_sha256': 'b08d497557295c08c2e34cba23ea380376f6a2139eadafad6da3a20d3fbe1828',
        'old_public_rows_sha256': 'b08d497557295c08c2e34cba23ea380376f6a2139eadafad6da3a20d3fbe1828',
        'old_transform_sha256': None,
        'public_row_count': 6,
        'work_id': 'schaff-history-vol-2',
    },
    'schaff-history-vol-3--schaff-history-vol-3-retained-electronic-witness': {
        'acceptance_path': 'library/works/schaff-history-vol-3/forms/schaff-history-vol-3-retained-electronic/editions/schaff-history-vol-3-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': '32bfca5b9652b189937f7ad0fe82838057fab7928b9298669247fbd90ecd2ccf',
        'baseline_row_count': 6,
        'edition_id': 'schaff-history-vol-3-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical Philip Schaff volume 3 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States): historical Philip Schaff volume 3 text; private CCEL electronic witness preparation, source-described 1910 Scribner edition, with reserved file and formatting rights',
        'master_path': 'library/works/schaff-history-vol-3/forms/schaff-history-vol-3-retained-electronic/editions/schaff-history-vol-3-retained-electronic-witness/master.tei.xml',
        'master_sha256': '2e6543859618cd9dc2b40ed1956e8c0d0f0d3496bd057ecde9323f171ed71001',
        'old_private_rows_sha256': '2356ed81d30b8fda65e656a363ff150d4072469177caa6c44e664c956a90c0fe',
        'old_public_rows_sha256': '2356ed81d30b8fda65e656a363ff150d4072469177caa6c44e664c956a90c0fe',
        'old_transform_sha256': None,
        'public_row_count': 6,
        'work_id': 'schaff-history-vol-3',
    },
    'schaff-history-vol-4--schaff-history-vol-4-ccel-hcc4-electronic': {
        'acceptance_path': 'library/works/schaff-history-vol-4/forms/schaff-history-vol-4-ccel-hcc4-retained-en/editions/schaff-history-vol-4-ccel-hcc4-electronic/acceptance.json',
        'acceptance_sha256': '65afa4e492d0afd37864c3006db57482334fba5facd2867380206604e62b9ebd',
        'baseline_row_count': 2,
        'edition_id': 'schaff-history-vol-4-ccel-hcc4-electronic',
        'license_after': 'Public domain (United States): historical Philip Schaff volume 4 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States): historical Philip Schaff volume 4 text; private CCEL electronic witness preparation, source-described 1910 Scribner edition, with reserved file and formatting rights',
        'master_path': 'library/works/schaff-history-vol-4/forms/schaff-history-vol-4-ccel-hcc4-retained-en/editions/schaff-history-vol-4-ccel-hcc4-electronic/master.tei.xml',
        'master_sha256': '0d8ca9bb6bea8bdc9d3054bfe96a0c486550849e67eb8b6a12ee3f9d49742b13',
        'old_private_rows_sha256': '51967ed67d435ec190bbc62810efa239c2efbba878a72ac4ea31dc2d5273cba3',
        'old_public_rows_sha256': '51967ed67d435ec190bbc62810efa239c2efbba878a72ac4ea31dc2d5273cba3',
        'old_transform_sha256': None,
        'public_row_count': 2,
        'work_id': 'schaff-history-vol-4',
    },
    'schaff-history-vol-5--schaff-history-vol-5-retained-electronic-witness': {
        'acceptance_path': 'library/works/schaff-history-vol-5/forms/schaff-history-vol-5-retained-electronic/editions/schaff-history-vol-5-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': '6c288dd8ffd10ce15180a90813890eaa19f87d1651e7801d05dd6a4e33e01961',
        'baseline_row_count': 3,
        'edition_id': 'schaff-history-vol-5-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical David S. Schaff volume 5 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States): historical David S. Schaff volume 5 text; private CCEL electronic witness preparation, source-described 1907 Scribner edition, with reserved file and formatting rights',
        'master_path': 'library/works/schaff-history-vol-5/forms/schaff-history-vol-5-retained-electronic/editions/schaff-history-vol-5-retained-electronic-witness/master.tei.xml',
        'master_sha256': '56bc3a2841c72207f08ad4b31ee7949d14bb456787c3b96fb801d5bc8de50cf1',
        'old_private_rows_sha256': 'aeb7a8800e65560da2d1a4b47ea73ab0d2d2fc7718aafda9f71c1de875fed7fa',
        'old_public_rows_sha256': 'aeb7a8800e65560da2d1a4b47ea73ab0d2d2fc7718aafda9f71c1de875fed7fa',
        'old_transform_sha256': None,
        'public_row_count': 3,
        'work_id': 'schaff-history-vol-5',
    },
    'schaff-history-vol-6--schaff-history-vol-6-retained-electronic-witness': {
        'acceptance_path': 'library/works/schaff-history-vol-6/forms/schaff-history-vol-6-retained-electronic/editions/schaff-history-vol-6-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': '3175c5bf2f6e579fd0429adda0bf4a605ab6374bf6ddac6fd74fce58873fae3f',
        'baseline_row_count': 4,
        'edition_id': 'schaff-history-vol-6-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical David S. Schaff volume 6 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States): historical David S. Schaff volume 6 text; private CCEL electronic witness preparation, source-described 1910 Scribner edition, with reserved file and formatting rights',
        'master_path': 'library/works/schaff-history-vol-6/forms/schaff-history-vol-6-retained-electronic/editions/schaff-history-vol-6-retained-electronic-witness/master.tei.xml',
        'master_sha256': '63c144dc5b51c9855c030d6e0f1e35dbdf890364aa2fb5643f24559be99c2555',
        'old_private_rows_sha256': '1d7c618ea60565cb7b02b712c32917a5fce83049b04a7ec7b213440c26a91c5c',
        'old_public_rows_sha256': '974f27cb6469eb313eefffceef19cce0df3be8a378773a74d2cc8c6a56da0ed5',
        'old_transform_sha256': '6554a30dbd1d87f3cdd3c2b919c17e5a2e2b7b4302ffe5397874ff1b929a8fb4',
        'public_row_count': 4,
        'work_id': 'schaff-history-vol-6',
    },
    'schaff-history-vol-7--schaff-history-vol-7-retained-electronic-witness': {
        'acceptance_path': 'library/works/schaff-history-vol-7/forms/schaff-history-vol-7-retained-electronic/editions/schaff-history-vol-7-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': 'c979d8545c40ff2ccbef68cd5ea35748f9df828806b959ce98e4a17283969065',
        'baseline_row_count': 3,
        'edition_id': 'schaff-history-vol-7-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical Philip Schaff volume 7 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States): historical Philip Schaff volume 7 text; private CCEL electronic witness preparation, source-described 1910 Scribner edition, with reserved file and formatting rights',
        'master_path': 'library/works/schaff-history-vol-7/forms/schaff-history-vol-7-retained-electronic/editions/schaff-history-vol-7-retained-electronic-witness/master.tei.xml',
        'master_sha256': '11a9f6530a2b874acb4fd52cba414ac9575a158ba3555bdf07aae030ed2d18c5',
        'old_private_rows_sha256': '8df39cdc18239420175a17ce82ef1886e45466988858981a84608859a97532bb',
        'old_public_rows_sha256': '8df39cdc18239420175a17ce82ef1886e45466988858981a84608859a97532bb',
        'old_transform_sha256': None,
        'public_row_count': 3,
        'work_id': 'schaff-history-vol-7',
    },
    'schaff-history-vol-8--schaff-history-vol-8-retained-electronic-witness': {
        'acceptance_path': 'library/works/schaff-history-vol-8/forms/schaff-history-vol-8-retained-electronic/editions/schaff-history-vol-8-retained-electronic-witness/acceptance.json',
        'acceptance_sha256': '002cfed14939f382f8b880bd17936af6b65ad9db252a8d33ea39e2dae49453b0',
        'baseline_row_count': 6,
        'edition_id': 'schaff-history-vol-8-retained-electronic-witness',
        'license_after': 'Public domain (United States): historical Philip Schaff volume 8 text and historical apparatus; factual electronic-source credits retained; CCEL files and formatting excluded',
        'license_before': 'Public domain (United States): historical Philip Schaff volume 8 text; private CCEL electronic witness preparation, source-described 1910 Scribner edition, with reserved file and formatting rights',
        'master_path': 'library/works/schaff-history-vol-8/forms/schaff-history-vol-8-retained-electronic/editions/schaff-history-vol-8-retained-electronic-witness/master.tei.xml',
        'master_sha256': 'cbb870c6837ef7f74c01a44e0099ac7301b273f099db00e5ca0997be403d6df0',
        'old_private_rows_sha256': '126c3566672ff00039680e4a084783c2ce52891247447cde8a05a0c17f49e65d',
        'old_public_rows_sha256': '126c3566672ff00039680e4a084783c2ce52891247447cde8a05a0c17f49e65d',
        'old_transform_sha256': None,
        'public_row_count': 6,
        'work_id': 'schaff-history-vol-8',
    },
    'spurgeons-morning-evening--spurgeons-morning-evening-ccel-thml-electronic': {
        'acceptance_path': 'library/works/spurgeons-morning-evening/forms/spurgeons-morning-evening-english/editions/spurgeons-morning-evening-ccel-thml-electronic/acceptance.json',
        'acceptance_sha256': '38052dc4bf2dfd7b0b1ccab73e4c24123a5823b661742eee8f4edbd20b062053',
        'baseline_row_count': 1,
        'edition_id': 'spurgeons-morning-evening-ccel-thml-electronic',
        'license_after': 'Public domain (United States): identified historical Charles Haddon Spurgeon devotional text; extracted underlying text sourced via CCEL.org; modern homepage instruction, files and formatting excluded',
        'license_before': 'Public domain (United States) for identified historical devotional text only; CCEL educational and noncommercial electronic-source terms apply to private offline preparation',
        'master_path': 'library/works/spurgeons-morning-evening/forms/spurgeons-morning-evening-english/editions/spurgeons-morning-evening-ccel-thml-electronic/master.tei.xml',
        'master_sha256': '9abbca4ffd8498fdc6f7867772a8caf32cb19cbaa0c5e96580f5ea58b9365023',
        'old_private_rows_sha256': '2e39f8ae7bf26b6d3e3482f09f24f001cf00f0a3d587790b42278069009eaf59',
        'old_public_rows_sha256': '6c2aa6002b7e5369c825544ae66b38832aec90fb0abef12719f037dd21a121ce',
        'old_transform_sha256': '84b2e4a3bf1d189cd1381e0d43655c5707f38669d517fe1f0b725e250260997f',
        'public_row_count': 1,
        'work_id': 'spurgeons-morning-evening',
    },
}


def _digest(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def requires_wrapper(item_id: str, license_label: str | None) -> bool:
    spec = SPECS.get(item_id)
    return spec is not None and license_label == spec["license_after"]


def uses_new_license(rows: list[dict[str, Any]], item_id: str) -> bool:
    spec = SPECS.get(item_id)
    if spec is None:
        return False
    labels = {row.get("license") for row in rows}
    if labels == {spec["license_after"]}:
        return True
    if labels == {spec["license_before"]}:
        return False
    raise PipelineError(f"{item_id}: mixed or unapproved publication license")


def _authority(item_id: str, acceptance_sha256: str | None,
               master_sha256: str | None) -> dict[str, Any]:
    spec = SPECS[item_id]
    if (acceptance_sha256 != spec["acceptance_sha256"]
            or master_sha256 != spec["master_sha256"]):
        raise PipelineError(f"{item_id}: rights wrapper source authority differs")
    return spec


def _license(rows: list[dict[str, Any]], before: str, after: str,
             item_id: str) -> list[dict[str, Any]]:
    if any(row.get("license") != before for row in rows):
        raise PipelineError(f"{item_id}: rights wrapper input license differs")
    return [dict(row, license=after) for row in rows]


def _edwards_scope(rows: list[dict[str, Any]], spec: dict[str, Any]
                   ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if (len(rows) != 21
            or [row.get("record_id") for row in rows] != spec["record_ids"]
            or [_digest(row) for row in rows] != spec["old_public_row_sha256"]):
        raise PipelineError("Edwards original twenty-one public carriers differ")
    retained = sorted(EDWARDS_RETAINED, key=lambda index: rows[index]["record_id"])
    if len({rows[index]["record_id"] for index in retained}) != 19:
        raise PipelineError("Edwards sermon record identities differ")
    return ([rows[index] for index in retained],
            [deepcopy(rows[index]) for index in EDWARDS_OMITTED])


def public_rows(rows: list[dict[str, Any]], *, item_id: str,
                acceptance_sha256: str | None, master_sha256: str | None
                ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Wrap the unchanged original projector route under an exact new label."""
    spec = _authority(item_id, acceptance_sha256, master_sha256)
    old_private = _license(rows, spec["license_after"], spec["license_before"], item_id)
    if len(old_private) != spec["baseline_row_count"] or _digest(old_private) != spec["old_private_rows_sha256"]:
        raise PipelineError(f"{item_id}: rights wrapper private rows differ")
    # The old label intentionally bypasses this wrapper in the dispatcher.
    from .public_rows import public_rows_with_omissions
    old_public, inner = public_rows_with_omissions(
        old_private, item_id=item_id, acceptance_sha256=acceptance_sha256,
        master_sha256=master_sha256)
    if (_digest(old_public) != spec["old_public_rows_sha256"]
            or (None if inner is None else _digest(inner)) != spec["old_transform_sha256"]):
        raise PipelineError(f"{item_id}: original public transform differs")
    omitted: list[dict[str, Any]] = []
    if item_id == EDWARDS_ITEM:
        old_public, omitted = _edwards_scope(old_public, spec)
    new_public = _license(old_public, spec["license_before"], spec["license_after"], item_id)
    if len(new_public) != spec["public_row_count"]:
        raise PipelineError(f"{item_id}: amended public row count differs")
    artifact = {
        "contract": CONTRACT, "item_id": item_id,
        "acceptance_sha256": acceptance_sha256, "master_sha256": master_sha256,
        "old_public_rows_sha256": spec["old_public_rows_sha256"],
        "new_public_rows_sha256": _digest(new_public),
        "inner": inner, "edwards_omitted_public_rows": omitted,
    }
    return new_public, artifact


def restore(rows: list[dict[str, Any]], artifact: dict[str, Any], *, item_id: str,
            acceptance_sha256: str | None, master_sha256: str | None
            ) -> list[dict[str, Any]]:
    """Rebuild the original private rows before the category checker runs."""
    spec = _authority(item_id, acceptance_sha256, master_sha256)
    if (not isinstance(artifact, dict)
            or set(artifact) != {"contract", "item_id", "acceptance_sha256", "master_sha256",
                                 "old_public_rows_sha256", "new_public_rows_sha256", "inner",
                                 "edwards_omitted_public_rows"}
            or artifact["contract"] != CONTRACT or artifact["item_id"] != item_id
            or artifact["acceptance_sha256"] != acceptance_sha256
            or artifact["master_sha256"] != master_sha256
            or artifact["old_public_rows_sha256"] != spec["old_public_rows_sha256"]
            or artifact["new_public_rows_sha256"] != _digest(rows)
            or len(rows) != spec["public_row_count"]):
        raise PipelineError(f"{item_id}: rights wrapper artifact or public rows differ")
    old_public = _license(rows, spec["license_after"], spec["license_before"], item_id)
    omitted = artifact["edwards_omitted_public_rows"]
    if item_id == EDWARDS_ITEM:
        if (not isinstance(omitted, list) or len(omitted) != 2
                or [_digest(row) for row in omitted]
                   != [spec["old_public_row_sha256"][index] for index in EDWARDS_OMITTED]):
            raise PipelineError("Edwards omitted collection carriers differ")
        positions = sorted(EDWARDS_RETAINED, key=lambda index: spec["record_ids"][index])
        if [row.get("record_id") for row in old_public] != [spec["record_ids"][index] for index in positions]:
            raise PipelineError("Edwards public sermon order differs")
        restored: list[dict[str, Any] | None] = [None] * 21
        for index, row in zip(positions, old_public, strict=True):
            restored[index] = row
        for index, row in zip(EDWARDS_OMITTED, omitted, strict=True):
            restored[index] = deepcopy(row)
        if any(row is None for row in restored):
            raise PipelineError("Edwards original row scope could not be restored")
        old_public = [row for row in restored if row is not None]
    elif omitted != []:
        raise PipelineError(f"{item_id}: unexpected omitted rows")
    if _digest(old_public) != spec["old_public_rows_sha256"]:
        raise PipelineError(f"{item_id}: original public rows did not reconstruct")
    inner = artifact["inner"]
    if (None if inner is None else _digest(inner)) != spec["old_transform_sha256"]:
        raise PipelineError(f"{item_id}: inner transform differs")
    if inner is not None:
        from .public_rows import restore_private_source_locations
        old_private = restore_private_source_locations(
            old_public, inner, item_id=item_id,
            acceptance_sha256=acceptance_sha256, master_sha256=master_sha256)
    else:
        old_private = old_public
    if _digest(old_private) != spec["old_private_rows_sha256"]:
        raise PipelineError(f"{item_id}: original private rows did not reconstruct")
    return _license(old_private, spec["license_before"], spec["license_after"], item_id)
