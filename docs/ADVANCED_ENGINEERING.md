# Advanced engineering: entity resolution

`knowledge_twin.resolution` adds deterministic candidate matching before graph insertion.

Names are Unicode-normalized, accent-insensitive, case-folded and tokenized. Candidate scoring
combines character-sequence similarity with token overlap, while exact normalized matches receive a
score of 1.0. Results are stable because ties are ordered by entity identifier.

This module is deliberately transparent rather than embedding a black-box model. It is useful as a
high-precision first stage before optional embedding/LLM resolution, and the threshold remains an
explicit caller-controlled policy.
