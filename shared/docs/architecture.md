# MVP Architecture

1. Telegram webhook writes raw payloads into `messages`.
2. Rule router handles cheap deterministic paths first.
3. Semantic router is only called when rules cannot classify.
4. Execution layer reads FAQ or knowledge chunks.
5. Confidence gate blocks low-confidence auto-replies.
6. Humanizer rewrites a grounded answer into natural support language.
7. Handoff sends a summary into the internal Telegram support group.
