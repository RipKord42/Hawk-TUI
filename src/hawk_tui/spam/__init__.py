# =============================================================================
# Spam Module
# =============================================================================
# Client-side spam filtering using Naive Bayes classification.
#
# Unlike server-side spam filters, this one:
#   - Learns from YOUR email patterns
#   - Can be trained with "Mark as Junk" / "Not Junk" actions
#   - Works offline
#   - Doesn't depend on server capabilities
#
# The classifier uses a bag-of-words model with Naive Bayes. It's simple,
# fast, and surprisingly effective for spam detection.
# =============================================================================

from hawk_tui.spam.classifier import SpamClassifier
from hawk_tui.spam.tokenizer import Tokenizer

__all__ = ["SpamClassifier", "Tokenizer"]
