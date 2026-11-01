"""
Top management team (TMT) role agents for LLM (large language model: a program
trained on vast amounts of text to write likely continuations) simulation.

An agent is a language model given a name, a role and instructions. This folder
defines the six simulated executives and the researcher agent that observes and
questions them.

-------------------------------------------------------------------------------
HOW ROLE DEFINITIONS ARE CREATED (AND RELATION TO RESEARCH)
-------------------------------------------------------------------------------
Each role is implemented as a prompt (the text sent to a model to get one reply) template: a short functional portrait
(CEO, CTO, COO, CMO, product strategy, product design) plus optional context
from ``context_definitions`` (industry dynamism, product novelty).

These portraits are not copied from a single empirical job-analysis study.
They are heuristic syntheses aligned with three literature streams:

1. Upper echelons / TMT composition and strategic choice  
   - Hambrick, D. C., & Mason, P. A. (1984). Upper echelons: The organization
     as a reflection of its top managers. *Academy of Management Review*,
     9(2), 193–206.  
   - Hambrick, D. C. (1994). Top management groups: A conceptual integration
     and reconsideration of the "team" label. *Research in Organizational
     Behavior*, 16, 171–214.  
   - Finkelstein, S., & Hambrick, D. C. (1996). *Strategic leadership: Top
     executives and their effects on organizations.* West Publishing.

2. Differentiated functional expertise and cross-functional integration  
   - Lawrence, P. R., & Lorsch, J. W. (1967). *Organization and environment:*
     *Managing differentiation and integration.* Harvard Business School Press.  
   - Chandler, A. D. (1962). *Strategy and structure: Chapters in the history of*
     *the American industrial enterprise.* MIT Press. (Classic view of general
     management and functional structure in large firms.)

3. Behavioral integration / debate in TMTs (why cross-role input matters)  
   - Simons, T., Pelled, L. H., & Smith, K. A. (1999). Making use of difference:
     Diversity, debate, and decision comprehensiveness in top management teams.
     *Academy of Management Journal*, 42(6), 662–673.

The Product Designer and Product Strategist labels mix TMT-style
functions with product-development practice; see comments in those modules
for design- and product-strategy-oriented citations.

For environment and innovation-type framing, see ``context_definitions.py``.
-------------------------------------------------------------------------------
"""

from .ceo_agent import create_ceo_agent
from .cto_agent import create_cto_agent
from .coo_agent import create_coo_agent
from .cmo_agent import create_cmo_agent
from .product_strategist_agent import create_product_strategist_agent
from .product_designer_agent import create_product_designer_agent

# Qualitative researcher (virtual ethnography — observer + panel debriefer: the
# researcher agent watches the team, then questions all six roles together).
# See protocols/ethnographic_protocol.yaml (the debrief's rules and topics).
from .qualitative_researcher_agent import (
    create_observer_agent,
    create_debriefer_agent,
    create_field_noter_agent,
    utterance_violates_protocol,
)
from .researcher_schemas import (
    ObservationSummary,
    PanelUtterance,
    PanelExchange,
    PanelResponse,
    Disagreement,
    RoleContribution,
    LoadedVocabUse,
)


