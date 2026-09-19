# Security

Entities and edges are supplied by the caller. There is no automatic entity extraction, trained semantic retrieval, LLM reasoning or graph database. Search uses substring matches and insertion-order ties. Adding an existing entity ID replaces its record. All graph state is in memory; evidence strings are not independently verified.

Use synthetic or explicitly authorized public data. Do not commit API keys, databases, model credentials, patient records or private employer material. Remote model adapters transmit supplied text to the configured endpoint; choose the provider deliberately.

For a suspected vulnerability, use GitHub private vulnerability reporting if enabled. Otherwise contact the maintainer privately through the [portfolio](https://maharshipatel-portfolio.vercel.app/). Do not put secrets or exploit payloads containing private data in a public issue. No response SLA is promised.
