"""Sub-dimensional lexicon for the openness rubric.

A rubric is a scoring guide; a lexicon is a fixed word list tied to a concept.
This file lists, for each part of the openness rubric, narrower items and the
word patterns that signal more or less openness. Software can count those
patterns in a text, and judge models (models that score a finished run) see
the items' names and definitions.

This module decomposes each of the 7 rubric dimensions in
`studies/openness_maneuvering/__init__.py` into 2 to 5 named
sub-dimensions (26 in all), each with a regex (a written pattern for finding text)
lexicon of pro-openness and anti-openness markers. The lexicon is the
methodological artefact
that powers Method A (anchored dictionary scoring, which counts words from a
fixed list) of the
sub-dimensional measurement layer.

Design principles
-----------------
1. **Literature-grounded.** Each parent dimension's sub-decomposition
   is anchored in the cited author (Henkel 2006, Chesbrough 2003,
   Teece 2007, Jacobides/Cennamo/Gawer 2018). The patterns are drawn
   either from those papers' own framing or from canonical industry
   artefacts (Llama 2/3 releases, OpenAI's GPT-4 technical report,
   Stability AI launches, Mistral release notes).

2. **Measurability is honest.** Each sub-dimension carries a
   measurability rating (H / M / L) indicating how reliably text
   alone can score it. High-measurability sub-dimensions (e.g.
   license-regime keywords) produce clean signal; low-measurability
   sub-dimensions (e.g. value-capture intent) are paraphrasable and
   warrant explicit confidence caveats in any paper that uses them.

3. **Patterns are regex, case-insensitive.** Word boundaries (`\\b`)
   are used where collisions matter; otherwise the patterns are
   designed to tolerate the common variant spellings (e.g.
   `licen[cs]e` to catch both US and UK spellings).

4. **Negation-tolerant downstream.** The scorer in
   `analysis/text_measures/dictionary.py` applies a ±3-token (three words
   either side) negation
   window when matching, so `"we will NOT keep our weights
   proprietary"` registers as pro-openness rather than anti-openness.
   The lexicon itself does NOT need to anticipate negation.

The lexicon is a **citable methodological artefact** in any paper
that uses it. See the docstring on `OPENNESS_SUBDIMENSION_LEXICON`
below for the contract every downstream consumer relies on.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


class SubDimensionEntry(TypedDict):
    """One sub-dimension's contract with the measurement layer."""

    parent_dimension: str
    """The rubric-dimension key from `studies/openness_maneuvering/__init__.py`."""

    display_name: str
    """Human-readable name for report output."""

    construct: str
    """Short construct definition (one sentence)."""

    pro_openness: List[str]
    """Regex patterns whose match counts as a pro-openness marker."""

    anti_openness: List[str]
    """Regex patterns whose match counts as an anti-openness marker."""

    measurability: str
    """One of 'H' / 'M' / 'L' — how reliable text alone is."""

    literature: str
    """Citation anchoring this sub-dimension's construct definition."""


# ---------------------------------------------------------------------------
# Dimension 1 — Component disclosure (Henkel 2006, selective revealing)
# ---------------------------------------------------------------------------
#
# Four sub-dimensions: what asset is disclosed, how deeply, under
# what license, and on what schedule. These are the most directly
# text-grounded of the 26 sub-dimensions — each has a concrete
# lexical surface in published artefacts (model cards, which are
# published summaries of a language model, license
# files, release announcements).

_D1_ASSET_CLASS_DISCLOSED: SubDimensionEntry = {
    "parent_dimension": "component_disclosure",
    "display_name": "Asset class disclosed",
    "construct": (
        "Which technical asset class is opened externally: model "
        "weights, training data, methods, evaluation code, or API "
        "surface."
    ),
    "pro_openness": [
        r"\brelease(?:d|s|ing)?\s+(?:the\s+|our\s+)?weights\b",
        r"\bopen[- ]?(?:weights|source(?:d)?)\b",
        r"\btraining\s+data\s+(?:is\s+|are\s+)?(?:public(?:ly)?\s+available|released|open)",
        r"\beval(?:uation)?\s+(?:code|harness|suite)\s+(?:is\s+|on\s+github|public(?:ly)?\s+available|open)",
        r"\bmodel\s+card\b",
        r"\bdataset\s+card\b",
        r"\bopen\s+(?:checkpoint|api)\b",
        r"\bweight[- ]available\b",
    ],
    "anti_openness": [
        r"\bproprietary\s+weights\b",
        r"\bclosed(?:[- ]source)?\s+(?:model|weights)\b",
        r"\binternal(?:ly)?[- ]only\s+(?:data|weights|model|api)\b",
        r"\bunreleased\b",
        r"\bkept\s+proprietary\b",
        r"\bnot\s+available\s+externally\b",
        r"\bcompetitive\s+(?:secret|advantage)\b",
    ],
    "measurability": "H",
    "literature": "Henkel 2006 (selective revealing)",
}

_D1_DEPTH_OF_DISCLOSURE: SubDimensionEntry = {
    "parent_dimension": "component_disclosure",
    "display_name": "Depth of disclosure",
    "construct": (
        "Full vs partial vs staged vs abstract-only disclosure of "
        "whatever asset class is named."
    ),
    "pro_openness": [
        r"\bfull(?:y|ly)?\s+open(?:[- ]source)?\b",
        r"\bcomplete\s+(?:release|disclosure)\b",
        r"\bevery\s+(?:weight|checkpoint|intermediate)\b",
        r"\b(?:end[- ]to[- ]end|full[- ]stack)\s+open\b",
    ],
    "anti_openness": [
        r"\bpartial(?:ly)?\s+(?:open|disclosed)\b",
        r"\bstaged\s+release\b",
        r"\bgated\s+access\b",
        r"\bapproved\s+researchers?\s+only\b",
        r"\bsummary\s+only\b",
        r"\bpaper\s+only\b",
        r"\babstract(?:ed)?\s+(?:detail|description)\b",
    ],
    "measurability": "H",
    "literature": "Henkel 2006 (selective revealing)",
}

_D1_LICENSE_REGIME: SubDimensionEntry = {
    "parent_dimension": "component_disclosure",
    "display_name": "License regime",
    "construct": (
        "Restrictiveness of the license under which assets are "
        "released — research-only, non-commercial, permissive, or "
        "restrictive commercial."
    ),
    "pro_openness": [
        r"\bMIT\s+licen[cs]e\b",
        r"\bApache(?:[- ]2\.0)?\s+licen[cs]e\b",
        r"\bApache\s+2\.0\b",
        r"\bpermissive\s+licen[cs]e\b",
        r"\bBSD\s+licen[cs]e\b",
        r"\bBSD[- ]3[- ]Clause\b",
        r"\bCC[- ]?BY(?:[- ]?\d(?:\.\d)?)?\b",
        r"\bpublic\s+domain\b",
        r"\bcommercial\s+use\s+(?:allowed|permitted)\b",
    ],
    "anti_openness": [
        r"\bnon[- ]commercial(?:\s+licen[cs]e)?\b",
        r"\bresearch[- ](?:only|use\s+only)\b",
        r"\bproprietary\s+licen[cs]e\b",
        r"\benterprise\s+licen[cs]e\b",
        r"\broyalty(?:\s+payment)?\b",
        r"\bcustom\s+licen[cs]e\b",
        r"\busage\s+restrictions?\b",
        r"\bacceptable\s+use\s+policy\s+restricting\b",
    ],
    "measurability": "H",
    "literature": "Henkel 2006; Stallman 1985 (license design)",
}

_D1_TEMPORAL_POSTURE: SubDimensionEntry = {
    "parent_dimension": "component_disclosure",
    "display_name": "Temporal posture",
    "construct": (
        "When disclosure happens — immediate at announcement, "
        "delayed, conditional, or never."
    ),
    "pro_openness": [
        r"\breleas(?:e|ed|ing)\s+today\b",
        r"\bavailable\s+now\b",
        r"\bon\s+(?:launch|day\s+one)\b",
        r"\bimmediate(?:ly)?\s+(?:public|available)\b",
        r"\bsame[- ]day\s+release\b",
    ],
    "anti_openness": [
        r"\bembargo(?:ed)?\b",
        r"\bdelayed\s+release\b",
        r"\bafter\s+(?:GA|launch|stabilization)\b",
        r"\bsubject\s+to.{0,30}review\b",
        r"\bnever\s+(?:open(?:ed)?|released?)\b",
        r"\bphased\s+(?:over|across)\s+(?:months|quarters)\b",
    ],
    "measurability": "M",
    "literature": "Henkel 2006 (timing as strategic lever)",
}


# ---------------------------------------------------------------------------
# Dimension 2 — Process openness (Chesbrough 2003, inbound OI)
# ---------------------------------------------------------------------------
#
# Four sub-dimensions: external code contribution, public governance,
# academic partnership, open development practices. Measurability is
# generally medium — surface markers exist but distinguishing genuine
# openness from "open-washing" requires semantic judgment.

_D2_EXTERNAL_CODE_CONTRIBUTION: SubDimensionEntry = {
    "parent_dimension": "process_openness",
    "display_name": "External code contribution",
    "construct": (
        "Whether external developers can submit code (pull requests, "
        "patches) upstream into the firm's core artefacts."
    ),
    "pro_openness": [
        r"\bpull\s+requests?\b",
        r"\bexternal\s+contributors?\b",
        r"\bcontributor\s+licen[cs]e\s+agreement\b",
        r"\bCLA\b",
        r"\bcommunity\s+contribution\b",
        r"\bupstream(?:ing)?(?:\s+patches)?\b",
        r"\baccept(?:s|ing)?\s+(?:external\s+)?PR\b",
        r"\bcontributing\.md\b",
    ],
    "anti_openness": [
        r"\binternal\s+contributors?\s+only\b",
        r"\bno\s+external\s+(?:commits|PR|contributions?)\b",
        r"\bclosed\s+development\b",
        r"\bread[- ]only\s+(?:mirror|fork)\b",
    ],
    "measurability": "M",
    "literature": "Chesbrough 2003 (inbound open innovation)",
}

_D2_PUBLIC_GOVERNANCE: SubDimensionEntry = {
    "parent_dimension": "process_openness",
    "display_name": "Public governance and RFC",
    "construct": (
        "Whether the firm's product roadmap, design documents, and "
        "decision processes are visible externally."
    ),
    "pro_openness": [
        r"\bpublic\s+roadmap\b",
        r"\bopen\s+RFC\b",
        r"\bRFC\s+process\b",
        r"\bdesign\s+doc(?:ument)?s?\s+in\s+public\b",
        r"\bcommunity\s+vote\b",
        r"\btechnical\s+steering\s+committee\b",
        r"\bopen\s+governance\b",
        r"\bpublic(?:ly)?\s+discuss(?:ed)?\s+(?:design|decision)\b",
    ],
    "anti_openness": [
        r"\binternal\s+roadmap\b",
        r"\bclosed[- ]door\s+(?:design|decision)\b",
        r"\bconfidential\s+strategy\b",
        r"\bproduct\s+decisions?\s+internal\b",
    ],
    "measurability": "M",
    "literature": "Chesbrough 2003; West & Gallagher 2006",
}

_D2_ACADEMIC_PARTNERSHIP: SubDimensionEntry = {
    "parent_dimension": "process_openness",
    "display_name": "Academic / research partnership",
    "construct": (
        "Whether the firm structurally partners with academic "
        "research — joint projects, residencies, fellowships, "
        "visiting researchers."
    ),
    "pro_openness": [
        r"\bjoint\s+research\b",
        r"\bacademic\s+partner(?:ship)?\b",
        r"\bresearch\s+collaborator(?:s|ship)?\b",
        r"\bresidency\s+program(?:me)?\b",
        r"\bvisiting\s+(?:researcher|scientist|scholar)\b",
        r"\bfellowship\s+program(?:me)?\b",
        r"\bpostdoc(?:toral)?\s+(?:position|programme)\b",
        r"\bdoctoral\s+collaboration\b",
    ],
    "anti_openness": [
        r"\bno\s+external\s+research(?:ers)?\b",
        r"\binternal\s+R&D\s+only\b",
        r"\bno\s+academic\s+(?:partner|engagement)\b",
    ],
    "measurability": "M",
    "literature": "Chesbrough 2003; Perkmann & Walsh 2007",
}

_D2_OPEN_DEVELOPMENT_PRACTICE: SubDimensionEntry = {
    "parent_dimension": "process_openness",
    "display_name": "Open development practice",
    "construct": (
        "Whether day-to-day development happens in the open — "
        "public issue trackers, public chat, transparent decisions."
    ),
    "pro_openness": [
        r"\bworking\s+in\s+the\s+open\b",
        r"\bpublic\s+issue\s+tracker\b",
        r"\bcommunity\s+(?:slack|discord|forum|matrix)\b",
        r"\btransparent\s+development\b",
        r"\bpublic\s+stand[- ]up\b",
        r"\bopen\s+(?:milestones|sprints?)\b",
    ],
    "anti_openness": [
        r"\binternal\s+jira\b",
        r"\bprivate\s+slack\b",
        r"\bclosed\s+beta\b",
        r"\binvite[- ]only\s+(?:access|preview)\b",
        r"\bbehind\s+(?:closed\s+doors|firewalls?)\b",
    ],
    "measurability": "M",
    "literature": "Raymond 1999; Chesbrough 2003",
}


# ---------------------------------------------------------------------------
# Dimension 3a — Boundary permeability INBOUND (Dahlander & Gann 2010)
# ---------------------------------------------------------------------------
#
# Inbound channels: hiring from competitors + academia, absorbing
# external research and open-source contributions, willingness to be
# influenced by ecosystem actors. New at rubric v0.2 — the v0.1 single-
# axis `boundary_permeability` was almost entirely outbound-flavoured
# (publications, talks, NDAs); inbound flow was undertested.

_D3I_EXTERNAL_HIRING: SubDimensionEntry = {
    "parent_dimension": "boundary_permeability_inbound",
    "display_name": "External hiring openness",
    "construct": (
        "Whether the firm actively hires talent from competitors, "
        "academia, and open-source communities, or operates a closed "
        "talent pipeline."
    ),
    "pro_openness": [
        r"\bhired\s+from\b",
        r"\bjoined\s+from\b",
        r"\b(?:recruit(?:ed|ing)|poach(?:ed|ing)?)\s+(?:from|out\s+of)\b",
        r"\bfrom\s+(?:academia|university|professor(?:ship)?|MIT|Stanford|CMU|Berkeley|Oxford|Cambridge)\b",
        r"\bopen[- ]source\s+contributor\s+(?:joined|hired)\b",
        r"\bcross[- ]industry\s+hire\b",
        r"\bex[- ](?:Google|OpenAI|Anthropic|Meta|Microsoft|DeepMind)\b",
    ],
    "anti_openness": [
        r"\bgrown\s+from\s+within\b",
        r"\bpromote(?:d)?\s+internally\b",
        r"\bclosed\s+talent\s+pipeline\b",
        r"\binternal[- ]only\s+promotion\b",
        r"\bdo(?:es)?\s+not\s+hire\s+from\b",
    ],
    "measurability": "M",
    "literature": "Almeida & Kogut 1999; Dahlander & Gann 2010 (inbound openness)",
}

_D3I_EXTERNAL_IDEA_ABSORPTION: SubDimensionEntry = {
    "parent_dimension": "boundary_permeability_inbound",
    "display_name": "External idea / artefact absorption",
    "construct": (
        "Whether the firm absorbs external work — open-source code, "
        "published research, third-party standards, partner-firm "
        "designs — into its own stack and roadmap, or insists on "
        "first-party origin for all components."
    ),
    "pro_openness": [
        r"\bbuilt\s+on\s+(?:top\s+of\s+)?(?:open[- ]source|llama|huggingface|pytorch|jax)\b",
        r"\badopt(?:ed|ing)?\s+(?:standard|protocol|spec)\b",
        r"\bcited\s+(?:paper|research|work)\b",
        r"\binfluenced\s+by\b",
        r"\bborrow(?:ed|ing)?\s+from\b",
        r"\bfork(?:ed|ing)?\s+from\b",
        r"\bdepends?\s+on\s+(?:external|open[- ]source)\b",
        r"\bupstream(?:ed)?\b",
    ],
    "anti_openness": [
        r"\bbuilt\s+from\s+scratch\b",
        r"\bfirst[- ]party\s+(?:only|stack)\b",
        r"\bproprietary\s+(?:stack|fork)\b",
        r"\bNIH\s+(?:problem|posture)\b",
        r"\bnot[- ]invented[- ]here\b",
        r"\bclean[- ]room\s+implementation\b",
    ],
    "measurability": "M",
    "literature": "Laursen & Salter 2006 (external search breadth); Dahlander & Gann 2010",
}


# ---------------------------------------------------------------------------
# Dimension 3b — Boundary permeability OUTBOUND
# ---------------------------------------------------------------------------
#
# Outbound channels: publications, conference talks, departures (or
# tolerance of), NDAs / IP enforcement (lack thereof). Re-parented
# from the v0.1 single-axis `boundary_permeability` — these four
# sub-dimensions are predominantly about outbound flow.

_D3_PUBLICATION_INTENSITY: SubDimensionEntry = {
    "parent_dimension": "boundary_permeability_outbound",
    "display_name": "Publication intensity",
    "construct": (
        "How readily research moves from the firm into the public "
        "scientific record — papers, preprints, technical reports."
    ),
    "pro_openness": [
        r"\b(?:peer[- ]reviewed\s+)?paper\b",
        r"\bpre[- ]?print\b",
        r"\barxiv\b",
        r"\btechnical\s+report\b",
        r"\bwe\s+publish(?:ed)?\b",
        r"\bNeurIPS\b",
        r"\bICML\b",
        r"\bACL\b",
        r"\bCVPR\b",
        r"\bICLR\b",
        r"\bopen[- ]review\b",
        r"\bjournal\s+submission\b",
    ],
    "anti_openness": [
        r"\bdo(?:es)?\s+not\s+publish\b",
        r"\bunpublished\b",
        r"\binternal\s+report\s+only\b",
        r"\bno\s+(?:peer\s+review|arxiv\s+post)\b",
        r"\bpublication\s+embargo\b",
    ],
    "measurability": "H",
    "literature": "Henkel 2006; Cohen, Nelson & Walsh 2002",
}

_D3_TALENT_FLOW: SubDimensionEntry = {
    "parent_dimension": "boundary_permeability_outbound",
    "display_name": "Talent flow",
    "construct": (
        "Whether researchers and engineers can flow across the firm "
        "boundary — hiring from + losing to competitors, dual "
        "affiliations."
    ),
    "pro_openness": [
        r"\bhired\s+from\b",
        r"\bjoined\s+from\b",
        r"\bdual(?:[- ]\s)?affiliat(?:ed|ion)\b",
        r"\bjoint\s+appointment\b",
        r"\bsabbatical\s+at\b",
        r"\bcross[- ]post(?:ed|ing)?\b",
        r"\bcourtesy\s+appointment\b",
    ],
    "anti_openness": [
        r"\bnon[- ]compete\b",
        r"\bgarden\s+leave\b",
        r"\brestricted\s+post[- ]employment\b",
        r"\bcooling[- ]off\s+period\b",
        r"\btalent\s+(?:retention|moat)\b",
    ],
    "measurability": "M",
    "literature": "OI broad literature; Almeida & Kogut 1999",
}

_D3_PUBLIC_PRESENCE: SubDimensionEntry = {
    "parent_dimension": "boundary_permeability_outbound",
    "display_name": "Public presence",
    "construct": (
        "How visible employees are externally — conference talks, "
        "podcasts, public writing."
    ),
    "pro_openness": [
        r"\bkeynote\b",
        r"\bconference\s+talk\b",
        r"\bpodcast\s+(?:appearance|interview)\b",
        r"\bpublic\s+talk\b",
        r"\btech\s+talk\b",
        r"\bblog\s+post\s+by\b",
        r"\bopen\s+lecture\b",
    ],
    "anti_openness": [
        r"\bno\s+external\s+speaking\b",
        r"\bmedia[- ]trained\b",
        r"\bpre[- ]approved\s+comms\b",
        r"\bnda\s+for\s+(?:talks|interviews)\b",
    ],
    "measurability": "M",
    "literature": "Henkel 2006; Allen 1983 (collective invention)",
}

_D3_NDA_IP_ENFORCEMENT: SubDimensionEntry = {
    "parent_dimension": "boundary_permeability_outbound",
    "display_name": "NDA / IP enforcement intensity",
    "construct": (
        "How aggressively the firm uses NDAs, trade-secret framing, "
        "and IP litigation to police its boundary."
    ),
    "pro_openness": [
        r"\bno\s+NDA(?:s)?\b",
        r"\bopen\s+IP\s+policy\b",
        r"\bdedicated\s+to\s+the\s+public\s+domain\b",
        r"\bdefensive\s+patent(?:ing)?\s+only\b",
    ],
    "anti_openness": [
        r"\b(?:trade\s+)?secret(?:s)?\b",
        r"\bnon[- ]disclosure(?:\s+agreement)?\b",
        r"\bconfidential\b",
        r"\bIP\s+enforcement\b",
        r"\bpatent\s+(?:claim|portfolio)\b",
        r"\binfring(?:e|ement|ing)\b",
        r"\bsuing?\s+for\s+IP\b",
    ],
    "measurability": "M",
    "literature": "Cohen, Nelson & Walsh 2000 (appropriability)",
}


# ---------------------------------------------------------------------------
# Dimension 4 — Ecosystem orchestration
# (Jacobides, Cennamo & Gawer 2018)
# ---------------------------------------------------------------------------
#
# Four sub-dimensions: developer programs, partner incentives,
# standards-body participation, hub-vs-node framing. The last is
# the most paraphrase-prone — dictionary-only scoring is brittle
# here; embedding-method support (comparing texts through numbers that stand
# for their meaning) is essential.

_D4_DEVELOPER_PROGRAMS: SubDimensionEntry = {
    "parent_dimension": "ecosystem_orchestration",
    "display_name": "Developer programs",
    "construct": (
        "Active investment in growing a developer base around the "
        "firm's APIs — SDKs, devrel, hackathons, grants."
    ),
    "pro_openness": [
        r"\bSDK\b",
        r"\bdeveloper\s+(?:program(?:me)?|relations|advocacy)\b",
        r"\bdevrel\b",
        r"\bhackathon\b",
        r"\bdeveloper\s+(?:grant|credits?)\b",
        r"\bstartup\s+program(?:me)?\b",
        r"\bcompute\s+credits?\s+for\s+developers?\b",
    ],
    "anti_openness": [
        r"\bno\s+developer\s+program(?:me)?\b",
        r"\binternal[- ]only\s+SDK\b",
        r"\bno\s+third[- ]party\s+(?:apps|integrations)\b",
    ],
    "measurability": "M",
    "literature": "Jacobides, Cennamo & Gawer 2018; Gawer 2014",
}

_D4_PARTNER_INCENTIVES: SubDimensionEntry = {
    "parent_dimension": "ecosystem_orchestration",
    "display_name": "Partner / complementor incentives",
    "construct": (
        "Whether the firm structurally rewards complementors — "
        "marketplaces, revenue share, certified-partner programs."
    ),
    "pro_openness": [
        r"\bpartner\s+program(?:me)?\b",
        r"\bmarketplace\b",
        r"\brevenue\s+share\b",
        r"\bapp\s+store\b",
        r"\bcertified\s+partner\b",
        r"\bcomplementor\s+(?:fund|grant|incentive)\b",
        r"\baffiliate\s+program(?:me)?\b",
    ],
    "anti_openness": [
        r"\bdirect\s+sales\s+only\b",
        r"\bno\s+marketplace\b",
        r"\bpipeline\s+(?:is\s+not|isn'?t)\s+ecosystem\b",
        r"\bvertical(?:ly)?\s+integrated\s+go[- ]to[- ]market\b",
    ],
    "measurability": "M",
    "literature": "Jacobides, Cennamo & Gawer 2018",
}

_D4_STANDARDS_PARTICIPATION: SubDimensionEntry = {
    "parent_dimension": "ecosystem_orchestration",
    "display_name": "Standards-body participation",
    "construct": (
        "Active involvement in industry-standards bodies and "
        "consortia — W3C, ISO, IEEE, MLCommons, working groups."
    ),
    "pro_openness": [
        r"\bW3C\b",
        r"\bIEEE\b",
        r"\bISO\b",
        r"\bworking\s+group\b",
        r"\bstandards\s+body\b",
        r"\bconsortium\b",
        r"\bMLCommons\b",
        r"\bIETF\b",
        r"\bjoint\s+standard\b",
    ],
    "anti_openness": [
        r"\bproprietary\s+standard\b",
        r"\bour\s+own\s+standard\b",
        r"\bno\s+standards\s+(?:involvement|participation)\b",
        r"\bde[- ]facto\s+standard\s+(?:we\s+set|under\s+our\s+control)\b",
    ],
    "measurability": "M",
    "literature": "Jacobides, Cennamo & Gawer 2018; Farrell & Saloner 1985",
}

_D4_HUB_VS_NODE_FRAMING: SubDimensionEntry = {
    "parent_dimension": "ecosystem_orchestration",
    "display_name": "Hub-vs-node framing",
    "construct": (
        "How the firm linguistically positions itself relative to "
        "its market — as a platform / ecosystem hub vs as a vertical "
        "competitor."
    ),
    "pro_openness": [
        r"\bplatform\b",
        r"\becosystem\b",
        r"\bcomplementors?\b",
        r"\bcoordinate(?:s|d)?\s+(?:the\s+)?ecosystem\b",
        r"\borchestrate(?:s|d)?\s+(?:the\s+)?ecosystem\b",
        r"\benable\s+complementors?\b",
        r"\benable\s+the\s+(?:long\s+tail|developer\s+ecosystem)\b",
    ],
    "anti_openness": [
        r"\bpipeline(?:\s+(?:model|approach|strategy))?\b",
        r"\bdirect\s+competitor\b",
        r"\bwe\s+own\s+the\s+(?:full\s+)?stack\b",
        r"\bvertical(?:ly)?\s+integrated\b",
        r"\bfull[- ]stack\s+(?:control|integration)\b",
        r"\bend[- ]to[- ]end\s+ownership\b",
    ],
    "measurability": "M",
    "literature": "Jacobides, Cennamo & Gawer 2018",
}


# ---------------------------------------------------------------------------
# Dimension 5 — Value capture posture (Teece 2007)
# ---------------------------------------------------------------------------
#
# Five sub-dimensions: monetisation mechanism, IP enforcement,
# network-effect framing, switching cost / lock-in, indirect
# monetisation. This is the dimension where dictionary alone is
# weakest — strategic intent is highly paraphrasable. Method B
# (embedding-anchored) is essential here.

_D5_MONETISATION_MECHANISM: SubDimensionEntry = {
    "parent_dimension": "value_capture_posture",
    "display_name": "Primary monetisation mechanism",
    "construct": (
        "How the firm extracts revenue — direct sales / per-token / "
        "subscription / freemium / open-with-services / platform "
        "fee."
    ),
    "pro_openness": [  # participation-based mechanisms
        r"\bfreemium\b",
        r"\busage[- ]based\s+pricing\b",
        r"\bconsumption\s+pricing\b",
        r"\bopen\s+core(?:\s+model)?\b",
        r"\bservices?\s+revenue\b",
        r"\bplatform\s+fee\b",
        r"\bmarketplace\s+fee\b",
        r"\btransaction\s+fee(?:\s+as\s+monetisation)?\b",
    ],
    "anti_openness": [  # control-based mechanisms
        r"\benterprise\s+(?:tier|licen[cs]e)\b",
        r"\bseat\s+licen[cs]e\b",
        r"\bper[- ]seat(?:\s+pricing)?\b",
        r"\bpremium\s+tier\b",
        r"\bpricing\s+power\b",
        r"\bvalue[- ]based\s+pricing\b",
        r"\bnegotiated\s+(?:enterprise\s+)?contracts?\b",
    ],
    "measurability": "M",
    "literature": "Teece 2007; West 2003",
}

_D5_IP_ENFORCEMENT: SubDimensionEntry = {
    "parent_dimension": "value_capture_posture",
    "display_name": "IP enforcement intensity",
    "construct": (
        "How aggressively the firm uses patents, trade secrets, and "
        "litigation to defend its monetisation posture."
    ),
    "pro_openness": [
        r"\bdedicated\s+to\s+the\s+public\s+domain\b",
        r"\bwe\s+(?:do\s+not|don'?t)\s+patent\b",
        r"\bdefensive\s+(?:patent|only)\b",
        r"\bpatent\s+pledge\b",
        r"\bcovenant\s+not\s+to\s+(?:sue|assert)\b",
    ],
    "anti_openness": [
        r"\bpatent\s+portfolio\b",
        r"\bpatent\s+claim(?:s)?\b",
        r"\binjunction\b",
        r"\binfring(?:e|ed|ing|ement)\b",
        r"\bwe\s+(?:will\s+)?sue\b",
        r"\bcease\s+and\s+desist\b",
        r"\bIP\s+lawsuit\b",
    ],
    "measurability": "M",
    "literature": "Teece 2007; Henkel 2006",
}

_D5_NETWORK_EFFECT_FRAMING: SubDimensionEntry = {
    "parent_dimension": "value_capture_posture",
    "display_name": "Network-effect framing",
    "construct": (
        "Explicit appeal to network effects or two-sided market "
        "dynamics as the firm's value-capture mechanism."
    ),
    "pro_openness": [
        r"\bnetwork\s+effect(?:s)?\b",
        r"\btwo[- ]sided\s+market\b",
        r"\bmulti[- ]sided\s+platform\b",
        r"\bthe\s+more\s+(?:users|developers|builders).{0,40}the\s+more\b",
        r"\bcross[- ]side\s+(?:effect|spillover)\b",
        r"\bdemand[- ]side\s+economies?\s+of\s+scale\b",
    ],
    "anti_openness": [
        # No clean anti-markers — absence is the signal. Scorer
        # treats this as low-measurability accordingly.
    ],
    "measurability": "L",
    "literature": "Teece 2007; Rochet & Tirole 2003",
}

_D5_SWITCHING_COST_LOCKIN: SubDimensionEntry = {
    "parent_dimension": "value_capture_posture",
    "display_name": "Switching cost / lock-in",
    "construct": (
        "Whether the firm builds or avoids proprietary formats, "
        "exclusive integrations, and customer lock-in."
    ),
    "pro_openness": [
        r"\binteroperab(?:le|ility)\b",
        r"\bportab(?:le|ility)\b",
        r"\bdata\s+export\b",
        r"\bno\s+lock[- ]in\b",
        r"\bstandard\s+(?:format|protocol)\b",
        r"\bvendor[- ]neutral\b",
        r"\bmigration\s+path\b",
    ],
    "anti_openness": [
        r"\block[- ]in\b",
        r"\bswitching\s+cost\b",
        r"\bproprietary\s+format\b",
        r"\bexclusive\s+partnership\b",
        r"\bnon[- ]portable\b",
        r"\bsticky\s+(?:product|integration)\b",
        r"\bdata\s+gravity\s+as\s+(?:strategy|moat)\b",
    ],
    "measurability": "L",
    "literature": "Teece 2007; Shapiro & Varian 1999",
}

_D5_INDIRECT_MONETISATION: SubDimensionEntry = {
    "parent_dimension": "value_capture_posture",
    "display_name": "Indirect monetisation",
    "construct": (
        "Whether the firm monetises an open / free core through "
        "indirect mechanisms — data-network effects, complementor "
        "fees, ecosystem rents."
    ),
    "pro_openness": [
        r"\bdata\s+network\s+effect(?:s)?\b",
        r"\becosystem\s+(?:rents|fees)\b",
        r"\bwe\s+monetise\s+the\s+(?:network|ecosystem)\b",
        r"\bopen[- ]core\s+revenue\s+model\b",
        r"\bcomplementor\s+(?:rent|fee)\b",
        r"\bindirect\s+monetisation\b",
    ],
    "anti_openness": [
        r"\bdirect\s+(?:sales|revenue)\s+only\b",
        r"\bno\s+indirect\s+monetisation\b",
        r"\bsingle[- ]source\s+revenue\b",
    ],
    "measurability": "L",
    "literature": "Teece 2007; Boudreau 2010",
}


# ---------------------------------------------------------------------------
# Dimension 6 — Temporal openness maneuvering (Henkel 2006 dynamic;
#               Alexy/Henkel/Wallin 2013)
# ---------------------------------------------------------------------------
#
# New at rubric v0.2. Captures the firm's reasoning about WHEN to open
# vs close — phased rollouts, conditional triggers, reversibility,
# sequencing across components. The other six dimensions score posture;
# this one scores the MOVE.

_D6_PHASED_ROLLOUT: SubDimensionEntry = {
    "parent_dimension": "temporal_openness_maneuvering",
    "display_name": "Phased-rollout language",
    "construct": (
        "Whether the firm explicitly stages openness across phases — "
        "'closed Phase 1, opening in Phase 2' or 'gated launch then "
        "broader release' — vs presenting openness as a static stance."
    ),
    "pro_openness": [
        r"\bPhase\s+[1-9]\b",
        r"\bphased\s+(?:rollout|launch|release|open(?:ing)?)\b",
        r"\bstaged\s+(?:rollout|disclosure|release)\b",
        r"\b(?:first|initial)\s+(?:gated|closed),?\s+(?:then|later)\s+(?:open|broader)\b",
        r"\bstart\s+(?:closed|gated)\s+(?:and\s+)?(?:then|later)\s+open\b",
        r"\bopen\s+up\s+(?:over\s+time|gradually|incrementally)\b",
        r"\bincremental(?:ly)?\s+open(?:ing)?\b",
    ],
    "anti_openness": [
        r"\bone[- ]shot\s+launch\b",
        r"\bbig[- ]bang\s+release\b",
        r"\bno\s+phased\s+plan\b",
        r"\bsingle\s+release\s+(?:date|moment)\b",
        r"\bpermanently\s+(?:closed|proprietary)\b",
    ],
    "measurability": "M",
    "literature": "Henkel 2006 (dynamic selective revealing); Lakhani & Tushman 2012",
}

_D6_CONDITIONAL_TRIGGERS: SubDimensionEntry = {
    "parent_dimension": "temporal_openness_maneuvering",
    "display_name": "Conditional triggers for opening",
    "construct": (
        "Whether the firm articulates explicit CONDITIONS that would "
        "trigger opening (or re-closing) — 'open the API once safety "
        "eval hits X', 'release the weights when the competitor "
        "ships', 'standardise once adoption stabilises'. Distinct "
        "from phasing — phasing is a plan, triggers are state-dependent."
    ),
    "pro_openness": [
        r"\bonce\s+(?:we|the\s+(?:market|standard|model))\b",
        r"\bwhen\s+(?:adoption|standards?|competitor)s?\b",
        r"\btrigger(?:ed|ing)?\s+(?:by|when|on)\b",
        r"\bcontingent\s+on\b",
        r"\bconditional\s+on\b",
        r"\bif\s+(?:and\s+only\s+if|when)\s+(?:we|the\s+market)\b",
        r"\bwait\s+until\b.*\bthen\s+open\b",
    ],
    "anti_openness": [
        r"\bunconditional(?:ly)?\s+(?:closed|proprietary)\b",
        r"\bno\s+trigger\s+to\s+open\b",
        r"\bregardless\s+of\s+(?:market|standard|competitor)\b",
    ],
    "measurability": "M",
    "literature": "Alexy, Henkel & Wallin 2013 (strategic selective revealing as sequencing)",
}

_D6_REVERSIBILITY: SubDimensionEntry = {
    "parent_dimension": "temporal_openness_maneuvering",
    "display_name": "Reversibility of openness moves",
    "construct": (
        "Whether the firm treats openness as REVERSIBLE — explicit "
        "plans to re-close, sunset clauses, ability to withdraw. The "
        "more reversible the firm's reasoning, the more it treats "
        "openness as a tactical lever rather than a commitment."
    ),
    "pro_openness": [
        r"\bsunset\s+(?:clause|date)\b",
        r"\bre[- ]close\b",
        r"\bwithdraw(?:al)?\s+(?:from|of)\s+(?:open|public)\b",
        r"\btime[- ]limited\s+(?:open|disclosure)\b",
        r"\bopen\s+window\b",
        r"\b(?:retract|rescind)\s+(?:license|disclosure)\b",
        r"\bdeprecate\s+the\s+open\s+(?:API|release)\b",
    ],
    "anti_openness": [
        r"\bpermanent(?:ly)?\s+open\b",
        r"\birrevocable\s+(?:license|release)\b",
        r"\bcannot\s+(?:re[- ]close|take\s+back)\b",
        r"\bonce\s+open,?\s+(?:always|stays)\s+open\b",
    ],
    "measurability": "L",
    "literature": "Henkel 2006 (dynamic capability framing); Alexy, Henkel & Wallin 2013",
}


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

OPENNESS_SUBDIMENSION_LEXICON: Dict[str, SubDimensionEntry] = {
    # D1 — Component disclosure
    "asset_class_disclosed":       _D1_ASSET_CLASS_DISCLOSED,
    "depth_of_disclosure":         _D1_DEPTH_OF_DISCLOSURE,
    "license_regime":              _D1_LICENSE_REGIME,
    "temporal_posture":            _D1_TEMPORAL_POSTURE,

    # D2 — Process openness
    "external_code_contribution":  _D2_EXTERNAL_CODE_CONTRIBUTION,
    "public_governance":           _D2_PUBLIC_GOVERNANCE,
    "academic_partnership":        _D2_ACADEMIC_PARTNERSHIP,
    "open_development_practice":   _D2_OPEN_DEVELOPMENT_PRACTICE,

    # D3a — Boundary permeability inbound (new at v0.2)
    "external_hiring":             _D3I_EXTERNAL_HIRING,
    "external_idea_absorption":    _D3I_EXTERNAL_IDEA_ABSORPTION,

    # D3b — Boundary permeability outbound (re-parented at v0.2)
    "publication_intensity":       _D3_PUBLICATION_INTENSITY,
    "talent_flow":                 _D3_TALENT_FLOW,
    "public_presence":             _D3_PUBLIC_PRESENCE,
    "nda_ip_enforcement":          _D3_NDA_IP_ENFORCEMENT,

    # D4 — Ecosystem orchestration
    "developer_programs":          _D4_DEVELOPER_PROGRAMS,
    "partner_incentives":          _D4_PARTNER_INCENTIVES,
    "standards_participation":     _D4_STANDARDS_PARTICIPATION,
    "hub_vs_node_framing":         _D4_HUB_VS_NODE_FRAMING,

    # D5 — Value capture posture
    "monetisation_mechanism":      _D5_MONETISATION_MECHANISM,
    "ip_enforcement":              _D5_IP_ENFORCEMENT,
    "network_effect_framing":      _D5_NETWORK_EFFECT_FRAMING,
    "switching_cost_lockin":       _D5_SWITCHING_COST_LOCKIN,
    "indirect_monetisation":       _D5_INDIRECT_MONETISATION,

    # D6 — Temporal openness maneuvering (new at v0.2)
    "phased_rollout_language":     _D6_PHASED_ROLLOUT,
    "conditional_triggers":        _D6_CONDITIONAL_TRIGGERS,
    "reversibility":               _D6_REVERSIBILITY,
}
"""All 26 sub-dimensions, keyed by the snake_case sub-dimension key.

Contract:
  - Every entry has a `parent_dimension` that exists in the active
    `JudgmentRubric` (`studies/openness_maneuvering/__init__.py`).
  - Every regex pattern compiles under `re.IGNORECASE`. (Verified by
    `tests/test_subdimension_lexicon.py`.)
  - `measurability` is one of `H` / `M` / `L`. The scorer in
    `analysis/text_measures/dictionary.py` uses this for the
    `measurability_weighted` aggregation in
    `06_subdimension_scores/per_dimension.csv`.
  - The lexicon is intentionally NOT exhaustive. New patterns can be
    added without changing the contract; deleting a pattern is a
    breaking change for any paper that already used the lexicon.
"""


# Convenience views for the scorer.

def subdimensions_for(parent_dimension: str) -> List[str]:
    """Return the sub-dimension keys that belong to a given parent."""
    return [
        key for key, entry in OPENNESS_SUBDIMENSION_LEXICON.items()
        if entry["parent_dimension"] == parent_dimension
    ]


def measurability_weight(rating: str) -> int:
    """Convert an `H` / `M` / `L` rating into the weight used by the
    `measurability_weighted` aggregation.

    H = 3, M = 2, L = 1. Per §9.8 decision 3 of the measurement plan.
    """
    return {"H": 3, "M": 2, "L": 1}.get(rating, 0)


# ===========================================================================
# Helpers used by the v0.4 sub-dimensional judging pipeline (PR-D; PR means
# pull request, a proposed set of changes)
# ===========================================================================

def parent_of(sub_dimension_key: str) -> str:
    """Return the parent-dimension key for a given sub-dimension key.

    Raises `KeyError` if `sub_dimension_key` is not in the lexicon —
    the aggregator uses this to enforce that every sub-dim assessment
    a judge emits matches a known parent.
    """
    entry = OPENNESS_SUBDIMENSION_LEXICON[sub_dimension_key]
    return entry["parent_dimension"]


def all_sub_dimension_keys() -> List[str]:
    """Return every sub-dimension key in canonical order.

    Canonical order = grouped by parent dimension (in the rubric's
    declared dimension order), then alphabetical within each group.
    Stable and reproducible — the judge's output, the aggregator's
    per-sub-dim α table, and the Excel report all key off this.
    """
    # Group keys by parent.
    by_parent: Dict[str, List[str]] = {}
    for key, entry in OPENNESS_SUBDIMENSION_LEXICON.items():
        by_parent.setdefault(entry["parent_dimension"], []).append(key)
    # Within each parent, sort alphabetically.
    for parent in by_parent:
        by_parent[parent].sort()
    # Emit in the rubric's parent-dim order. This list is the
    # authoritative ordering of the 7 dimensions; keeping it here
    # rather than importing from `studies.openness_maneuvering.__init__`
    # avoids a circular import (the lexicon is loaded before the
    # rubric in `studies/__init__.py`).
    parent_order = (
        "component_disclosure",
        "process_openness",
        "boundary_permeability_inbound",
        "boundary_permeability_outbound",
        "ecosystem_orchestration",
        "value_capture_posture",
        "temporal_openness_maneuvering",
    )
    out: List[str] = []
    for parent in parent_order:
        out.extend(by_parent.get(parent, []))
    return out


def render_sub_dimensions_for_prompt() -> str:
    """Render the lexicon as a prompt-block listing every sub-dimension
    grouped by parent.

    Output shape::

        ## boundary_permeability_outbound
          - outbound_publication_intensity
            "(short construct definition sentence)"
          - outbound_talent_flow_out
            "(short construct definition sentence)"
          ...

    Consumed by the judge-prompt template (PR-D commit 3/6) so the
    LLM (large language model) sees the full 26-sub-dim taxonomy + each
    sub-dim's one-
    sentence construct definition. The judge then produces exactly
    one `SubDimensionAssessment` per key.
    """
    lines: List[str] = []
    last_parent: str = ""
    for key in all_sub_dimension_keys():
        entry = OPENNESS_SUBDIMENSION_LEXICON[key]
        parent = entry["parent_dimension"]
        if parent != last_parent:
            lines.append(f"\n## {parent}")
            last_parent = parent
        construct = entry.get("construct", "").strip()
        lines.append(f"  - {key}")
        if construct:
            lines.append(f"      {construct}")
    return "\n".join(lines).lstrip("\n")
