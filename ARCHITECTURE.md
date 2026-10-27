# Touchline on Azure — reference architecture

## Production blueprint

```
 Synthetic Match Simulator (Python engine, containerized)
        |  JSON event stream (x, y, event, t)
        v
 Azure Event Hubs  (event ingestion, ordered partitions per match)
        v
 Azure Functions / Container Apps worker  (stage 2-3: metrics + explainability)
        v
 Microsoft Foundry (Azure OpenAI)  (stage 4: agent narratives, multilingual feed)
        v                       v
 Broadcast Overlay API      Fan Studio Web App
 (FastAPI on ACA)           (static SPA on Front Door / Blob CDN)
```

## Mapping the demo to the blueprint

| Demo component | Production Azure service |
| --- | --- |
| `backend/api/server.py` SSE stream | Azure Event Hubs + Azure Functions trigger |
| `backend/agents/agents.py` `_llm` | Microsoft Foundry (Azure OpenAI) deployment |
| Orchestrator blackboard | Azure Cosmos DB (shared agent state) |
| FastAPI container | Azure Container Apps (`azure-container-app.yaml`) |
| Static studio UI | Azure Static Web Apps / Front Door |

## Why the orchestrator is Azure-ready

- Agents communicate only through the shared blackboard (state handoffs), so the
  blackboard can be lifted into Cosmos DB without touching agent code.
- The `_llm` adapter is the single call site for model inference; pointing it at a
  Foundry deployment is one env-var change (`AZURE_OPENAI_ENDPOINT`,
  `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT`).
- The metrics engine is a pure function of the event stream, so it runs unchanged
  inside an Azure Functions worker consuming Event Hubs.
- `azure-container-app.yaml` deploys the API container with a health probe on
  `/health` and scale-to-zero.

## Latency budget

The challenge asks for event-to-insight within live broadcast thresholds (<2s).
In the demo, metrics + insight generation per tick complete in well under 10ms
(see tests); the SSE pacing governs playback speed, not compute.
