---
id: DEV-REFERENCE
title: Reference Implementation
domain: integration
version: 1.0.0
status: approved
approved_by: PO
last_review: 2026-07-19
review_after: 2027-01-19
owner: Alpha3S
---

# Purpose

Pseudocode tham chiếu để dev hiểu luồng, không ràng buộc Python/TypeScript/framework cụ thể.

# Core Interfaces

```text
KnowledgeLoader
AssetValidator
KnowledgeUnitBuilder
Indexer
IntentRouter
ToolRouter
Retriever
Reranker
ContextBuilder
PromptAssembler
LLMClient
ResponseValidator
ConversationStateStore
HandoffService
```

# Ingestion

```python
for file in discover_markdown(roots):
    asset = loader.parse(file)
    validator.require_schema(asset)
    if asset.status != "approved":
        continue
    for unit in unit_builder.from_headings(asset):
        index.upsert(unit)

publish_index_after_tests()
```

# Runtime

```python
def process(message, conversation_id):
    state = state_store.load(conversation_id)
    route = router.classify(message, state)

    if route.requires_handoff:
        return handoff.create(route, state)

    tool_results = tool_router.execute(route, message, state)
    units = retriever.search(message, state, route)
    units = reranker.rank_and_dedupe(units)

    context = context_builder.build(
        state=state,
        tool_results=tool_results,
        units=units,
        budget=config.context_budget,
    )

    prompt = prompt_assembler.assemble(context, message)
    candidate = llm.generate(prompt)
    result = validator.validate(candidate, context, route)

    if not result.passed:
        result = fallback.handle(result, context, route)

    state_store.apply(conversation_id, result.state_update)
    audit.log_provenance(result)
    return result.response
```

# Source Resolution

```python
def resolve(sources):
    valid = remove_draft_superseded_expired(sources)
    ranked = apply_source_priority(valid)
    if authoritative_conflict(ranked):
        raise SourceConflict()
    return ranked.best()
```

# Repository Routing

```text
SKL-BRAND-* → skills/brand
SKL-PRD-*   → skills/product
SKL-SAL-*   → skills/sales
SKL-CON-*   → skills/conversation
SKL-FAQ-*   → skills/faq
PBK-*       → playbooks
KG/PA/RT/EV → docs corresponding domain
```

# Important Note

Reference code không phải production-ready security implementation. Dev phải bổ sung auth, privacy, retry, observability và channel-specific behavior.
