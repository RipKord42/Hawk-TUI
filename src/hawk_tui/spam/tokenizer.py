# =============================================================================
# Email Tokenizer for Spam Classification
# =============================================================================
# Converts email content into tokens (features) for the spam classifier.
#
# Good tokenization is key to spam detection. We extract:
#   - Words from subject and body
#   - Email addresses
#   - URLs and domains
#   - Special patterns (ALL CAPS, !!!, $$$, etc.)
#
# Tokens are normalized (lowercased, stripped) and filtered (stop words,
# very short tokens, etc.)
# =============================================================================

import re
from dataclasses import dataclass


@dataclass
class TokenizerConfig:
    """
    Configuration for email tokenization.

    Attributes:
        min_token_length: Minimum length for a token to be included.
        max_token_length: Maximum length (longer tokens are truncated).
        include_headers: Include tokens from email headers.
        include_urls: Extract and include URL/domain tokens.
        normalize_case: Convert all tokens to lowercase.
    """
    min_token_length: int = 2
    max_token_length: int = 50
    include_headers: bool = True
    include_urls: bool = True
    normalize_case: bool = True


class Tokenizer:
    """
    Converts email content into tokens for spam classification.

    The tokenizer extracts features from email content that are
    predictive of spam/ham classification.

    Usage:
        >>> tokenizer = Tokenizer()
        >>> tokens = tokenizer.tokenize(subject="Buy now!!!", body="...")
        >>> print(tokens)
        ['buy', 'now', 'TOKEN_EXCLAMATION', ...]
    """

    # Common English stop words (not useful for classification)
    STOP_WORDS = frozenset([
        "a", "an", "the", "and", "or", "but", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might", "can", "to",
        "of", "in", "for", "on", "with", "at", "by", "from", "as", "into",
        "through", "during", "before", "after", "above", "below", "this",
        "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
        "you", "your", "he", "she", "they", "them", "his", "her", "their",
    ])

    # Patterns that are strong spam indicators
    SPECIAL_PATTERNS = [
        (r'!!+', 'TOKEN_EXCLAMATION'),      # Multiple exclamation marks
        (r'\$\$+', 'TOKEN_MONEY'),           # Dollar signs
        (r'[A-Z]{5,}', 'TOKEN_ALLCAPS'),     # ALL CAPS words (5+ chars)
        (r'\d{3}-\d{3}-\d{4}', 'TOKEN_PHONE'),  # Phone numbers
        (r'click\s+here', 'TOKEN_CLICKHERE'),   # "Click here"
        (r'act\s+now', 'TOKEN_ACTNOW'),         # "Act now"
        (r'limited\s+time', 'TOKEN_LIMITED'),   # "Limited time"
        (r'free\s+gift', 'TOKEN_FREEGIFT'),     # "Free gift"
    ]

    # URL pattern
    URL_PATTERN = re.compile(
        r'https?://(?:www\.)?([a-zA-Z0-9-]+(?:\.[a-zA-Z]{2,})+)',
        re.IGNORECASE
    )

    # Email pattern
    EMAIL_PATTERN = re.compile(
        r'[a-zA-Z0-9._%+-]+@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})',
        re.IGNORECASE
    )

    def __init__(self, config: TokenizerConfig | None = None) -> None:
        """
        Initialize the tokenizer.

        Args:
            config: Tokenizer configuration.
        """
        self.config = config or TokenizerConfig()

        # Pre-compile special patterns
        self._special_patterns = [
            (re.compile(pattern, re.IGNORECASE), token)
            for pattern, token in self.SPECIAL_PATTERNS
        ]

    def tokenize(
        self,
        *,
        subject: str = "",
        body: str = "",
        sender: str = "",
        headers: dict[str, str] | None = None,
    ) -> list[str]:
        """
        Tokenize email content.

        Args:
            subject: Email subject line.
            body: Email body (plain text preferred).
            sender: Sender email address.
            headers: Additional headers to analyze.

        Returns:
            List of tokens.
        """
        tokens: list[str] = []

        # Add special prefix for subject tokens (they're more predictive)
        if subject:
            subject_tokens = self._tokenize_text(subject)
            tokens.extend(f"SUBJ_{t}" for t in subject_tokens)

        # Tokenize body
        if body:
            tokens.extend(self._tokenize_text(body))

        # Extract special patterns
        full_text = f"{subject} {body}"
        for pattern, token_name in self._special_patterns:
            if pattern.search(full_text):
                tokens.append(token_name)

        # Extract URLs and domains
        if self.config.include_urls:
            tokens.extend(self._extract_urls(full_text))

        # Extract sender domain
        if sender:
            match = self.EMAIL_PATTERN.search(sender)
            if match:
                tokens.append(f"SENDER_DOMAIN_{match.group(1).lower()}")

        # Analyze headers
        if self.config.include_headers and headers:
            tokens.extend(self._analyze_headers(headers))

        return tokens

    def _tokenize_text(self, text: str) -> list[str]:
        """
        Basic text tokenization.

        Splits on whitespace and punctuation, normalizes, and filters.
        """
        # Remove HTML tags if present
        text = re.sub(r'<[^>]+>', ' ', text)

        # Split on non-word characters
        words = re.findall(r'\b[a-zA-Z0-9]+\b', text)

        tokens = []
        for word in words:
            # Normalize
            if self.config.normalize_case:
                word = word.lower()

            # Filter
            if len(word) < self.config.min_token_length:
                continue
            if len(word) > self.config.max_token_length:
                word = word[:self.config.max_token_length]
            if word in self.STOP_WORDS:
                continue

            tokens.append(word)

        return tokens

    def _extract_urls(self, text: str) -> list[str]:
        """Extract URL domain tokens from text."""
        tokens = []

        for match in self.URL_PATTERN.finditer(text):
            domain = match.group(1).lower()
            tokens.append(f"URL_DOMAIN_{domain}")

        return tokens

    def _analyze_headers(self, headers: dict[str, str]) -> list[str]:
        """
        Extract spam-indicative features from headers.

        Things like:
            - X-Mailer (mass mailing software)
            - Received path (suspicious relays)
            - Missing standard headers
        """
        tokens = []

        # Check for mass-mailing software
        x_mailer = headers.get("X-Mailer", "").lower()
        if any(spam_mailer in x_mailer for spam_mailer in
               ["phpmailer", "mailchimp", "sendgrid"]):
            tokens.append("HEADER_MASSMAILER")

        # Check for missing Message-ID (often forged)
        if not headers.get("Message-ID"):
            tokens.append("HEADER_NO_MESSAGEID")

        # Check for suspicious Reply-To (different from From)
        reply_to = headers.get("Reply-To", "")
        from_addr = headers.get("From", "")
        if reply_to and from_addr and reply_to.lower() != from_addr.lower():
            tokens.append("HEADER_REPLY_DIFFERS")

        return tokens
