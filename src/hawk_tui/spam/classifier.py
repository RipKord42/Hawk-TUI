# =============================================================================
# Naive Bayes Spam Classifier
# =============================================================================
# A simple but effective spam classifier using Naive Bayes.
#
# How it works:
#   1. During training, we count how often each token appears in spam vs ham
#   2. For classification, we calculate:
#      P(spam|tokens) ∝ P(spam) × ∏ P(token|spam)
#      P(ham|tokens) ∝ P(ham) × ∏ P(token|ham)
#   3. The class with higher probability wins
#
# We use log probabilities to avoid underflow and add Laplace smoothing
# to handle unseen tokens.
# =============================================================================

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from hawk_tui.spam.tokenizer import Tokenizer

if TYPE_CHECKING:
    from hawk_tui.core import Message


@dataclass
class ClassifierStats:
    """
    Statistics about the classifier.

    Attributes:
        spam_count: Number of spam messages trained on.
        ham_count: Number of ham (non-spam) messages trained on.
        token_count: Number of unique tokens in vocabulary.
    """
    spam_count: int = 0
    ham_count: int = 0
    token_count: int = 0


@dataclass
class TokenCounts:
    """
    Token frequency counts for spam classification.

    Attributes:
        spam: Count of times this token appeared in spam.
        ham: Count of times this token appeared in ham.
    """
    spam: int = 0
    ham: int = 0


class SpamClassifier:
    """
    Naive Bayes spam classifier.

    Learns from user feedback ("Mark as Junk" / "Not Junk") and
    classifies new messages.

    Usage:
        >>> classifier = SpamClassifier()
        >>> classifier.load()  # Load existing model if any
        >>> score = classifier.classify(message)
        >>> if score > 0.7:
        ...     print("Probably spam!")
        >>> classifier.train(message, is_spam=True)  # Learn from feedback
        >>> classifier.save()

    Attributes:
        tokenizer: Tokenizer for extracting features from emails.
        model_path: Path to save/load the model.
    """

    def __init__(
        self,
        tokenizer: Tokenizer | None = None,
        model_path: Path | None = None,
    ) -> None:
        """
        Initialize the spam classifier.

        Args:
            tokenizer: Tokenizer instance. Creates default if None.
            model_path: Path to model file. Uses XDG default if None.
        """
        self.tokenizer = tokenizer or Tokenizer()
        self.model_path = model_path

        # Training data
        self._spam_count = 0        # Number of spam messages trained
        self._ham_count = 0         # Number of ham messages trained
        self._tokens: dict[str, TokenCounts] = {}  # Token frequencies

        # Smoothing parameter (Laplace smoothing)
        self._alpha = 1.0

    @property
    def stats(self) -> ClassifierStats:
        """Get classifier statistics."""
        return ClassifierStats(
            spam_count=self._spam_count,
            ham_count=self._ham_count,
            token_count=len(self._tokens),
        )

    @property
    def is_trained(self) -> bool:
        """Returns True if the classifier has been trained."""
        return self._spam_count > 0 and self._ham_count > 0

    def classify(self, message: "Message") -> float:
        """
        Classify a message and return spam probability.

        Args:
            message: Message to classify.

        Returns:
            Spam probability (0.0 = definitely ham, 1.0 = definitely spam).
            Returns 0.5 if classifier is not trained.
        """
        if not self.is_trained:
            return 0.5  # Unknown

        # Extract tokens from message
        tokens = self.tokenizer.tokenize(
            subject=message.subject,
            body=message.body_text or message.body_html,
            sender=message.sender,
        )

        if not tokens:
            return 0.5  # Can't classify without tokens

        # Calculate log probabilities
        log_spam = self._log_probability(tokens, is_spam=True)
        log_ham = self._log_probability(tokens, is_spam=False)

        # Convert to probability using softmax
        # P(spam) = exp(log_spam) / (exp(log_spam) + exp(log_ham))
        # For numerical stability, subtract the max
        max_log = max(log_spam, log_ham)
        log_spam -= max_log
        log_ham -= max_log

        prob_spam = math.exp(log_spam)
        prob_ham = math.exp(log_ham)
        total = prob_spam + prob_ham

        return prob_spam / total if total > 0 else 0.5

    def train(self, message: "Message", *, is_spam: bool) -> None:
        """
        Train the classifier on a message.

        Call this when user marks a message as junk or not junk.

        Args:
            message: Message to learn from.
            is_spam: True if message is spam, False if ham.
        """
        # Extract tokens
        tokens = self.tokenizer.tokenize(
            subject=message.subject,
            body=message.body_text or message.body_html,
            sender=message.sender,
        )

        # Update counts
        if is_spam:
            self._spam_count += 1
        else:
            self._ham_count += 1

        # Update token frequencies
        for token in set(tokens):  # Use set to count each token once per message
            if token not in self._tokens:
                self._tokens[token] = TokenCounts()

            if is_spam:
                self._tokens[token].spam += 1
            else:
                self._tokens[token].ham += 1

    def untrain(self, message: "Message", *, was_spam: bool) -> None:
        """
        Remove a message's contribution from training.

        Use when user changes classification (was spam, now not spam).

        Args:
            message: Message to remove.
            was_spam: What the message was classified as.
        """
        tokens = self.tokenizer.tokenize(
            subject=message.subject,
            body=message.body_text or message.body_html,
            sender=message.sender,
        )

        # Update counts
        if was_spam:
            self._spam_count = max(0, self._spam_count - 1)
        else:
            self._ham_count = max(0, self._ham_count - 1)

        # Update token frequencies
        for token in set(tokens):
            if token in self._tokens:
                if was_spam:
                    self._tokens[token].spam = max(0, self._tokens[token].spam - 1)
                else:
                    self._tokens[token].ham = max(0, self._tokens[token].ham - 1)

    def _log_probability(self, tokens: list[str], *, is_spam: bool) -> float:
        """
        Calculate log probability of tokens given class.

        Uses Laplace smoothing to handle unseen tokens.
        """
        # Prior probability
        total = self._spam_count + self._ham_count
        if is_spam:
            log_prob = math.log((self._spam_count + self._alpha) / (total + 2 * self._alpha))
            class_count = self._spam_count
        else:
            log_prob = math.log((self._ham_count + self._alpha) / (total + 2 * self._alpha))
            class_count = self._ham_count

        # Token probabilities
        vocab_size = len(self._tokens)
        for token in tokens:
            if token in self._tokens:
                token_count = self._tokens[token].spam if is_spam else self._tokens[token].ham
            else:
                token_count = 0

            # Laplace-smoothed probability
            prob = (token_count + self._alpha) / (class_count + self._alpha * vocab_size)
            log_prob += math.log(prob)

        return log_prob

    def save(self, path: Path | None = None) -> None:
        """
        Save the classifier model to disk.

        Args:
            path: Path to save to. Uses self.model_path if None.
        """
        save_path = path or self.model_path
        if not save_path:
            from hawk_tui.config import Config
            save_path = Config.spam_model_path()

        data = {
            "version": 1,
            "spam_count": self._spam_count,
            "ham_count": self._ham_count,
            "tokens": {
                token: {"spam": counts.spam, "ham": counts.ham}
                for token, counts in self._tokens.items()
            },
        }

        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            json.dump(data, f)

    def load(self, path: Path | None = None) -> bool:
        """
        Load a classifier model from disk.

        Args:
            path: Path to load from. Uses self.model_path if None.

        Returns:
            True if model was loaded, False if no model exists.
        """
        load_path = path or self.model_path
        if not load_path:
            from hawk_tui.config import Config
            load_path = Config.spam_model_path()

        if not load_path.exists():
            return False

        try:
            with open(load_path) as f:
                data = json.load(f)

            self._spam_count = data["spam_count"]
            self._ham_count = data["ham_count"]
            self._tokens = {
                token: TokenCounts(spam=counts["spam"], ham=counts["ham"])
                for token, counts in data["tokens"].items()
            }
            return True
        except (json.JSONDecodeError, KeyError):
            return False

    def reset(self) -> None:
        """Reset the classifier to untrained state."""
        self._spam_count = 0
        self._ham_count = 0
        self._tokens.clear()
