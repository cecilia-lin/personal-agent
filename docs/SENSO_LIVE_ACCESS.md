# Senso live fact-check experiment

The requested experiment was timeboxed to ten minutes, starting November 20, 2026 at 22:22:20 UTC. It ended without a live fact-check response. This is **not** evidence that the API key or organization was denied access.

Official documentation confirms asynchronous `senso_check_text` / `senso_get_text_check` tools, a returned `check_id`, and per-claim `verified`, `conflict`, `unsupported`, and `not_verifiable` verdicts. However, the attempt to fetch the official REST specification was interrupted while the tool invocation was pending. No REST fact-check endpoint was confirmed or called, and no new documents were uploaded.

The implementation consequently preserves the existing retrieval path and labels its limited scope. Retrieved passages retain their identifiers; they are not promoted to supporting fact-check evidence. The provider reports `fact_check_verified: false`. Essential live claims remain unresolved and block proposals. The offline fixture journey remains explicitly labeled as a fixture.

The known desk-light claims are separate: Arc has a replaceable bulb; Fold has a replaceable light module; Halo has serviceable components. These are assertions selected from exact catalog descriptions to be checked, not verified facts. A changed or unknown description needs an explicit claim definition. A local `repairable` flag is not sufficient evidence.

To enable the live path later, confirm the official endpoint contract with the organization and key, obtain a real check ID and verdict with versioned supporting sources, then add the adapter and repeat the supported, contradicted/missing, unavailable, and stale-evidence cases. Do not infer support from retrieval similarity or keyword matches.

References: [Senso fact-check tool contract](https://docs.senso.ai/docs/mcp-server), [official REST specification](https://docs.senso.ai/specs/sdk-api.yaml).
