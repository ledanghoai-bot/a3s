# ADR-0003 --- Retrieval Strategy

## Status

Accepted

Alpha3S adopts Hybrid Retrieval:

-   Vector Search
-   BM25 / Keyword Search
-   Reranker

### Why

Hybrid retrieval improves recall for Vietnamese queries, product names,
SKUs and mixed-language questions.

### Recommendation

-   Chunk by heading
-   Keep metadata
-   Keep keywords
-   Retrieve Top-K then rerank before context building.
