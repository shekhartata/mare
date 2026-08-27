"""Semantic neighborhoods with partitioned prototypes. Never reads scoring labels.

Replaces hash/time shards: recursive distinctive-term splits, then k-medoid
partitions so leftover mixed buckets still get different embeddings.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from app.datagen.scale_corpus import TEXT_FIELDS
from app.indexing.topical_grouping import (
    document_text,
    strip_scoring_fields,
    tokenize,
)

MAX_PROTOTYPES = 4
MIN_SIDE = 8
MIN_SPLIT_FRAC = 0.18
MAX_SPLIT_FRAC = 0.82
EXAMPLE_CHARS = 180
MAX_SUMMARY_CHARS = 1600
MAX_GROUPS = 1500


def semantic_groups_from_docs(
    docs: Iterable[dict[str, Any]],
    *,
    tenant_id: str,
    collection: str,
    target_docs_per_group: int = 20,
    text_fields: tuple[str, ...] = TEXT_FIELDS,
    max_prototypes: int = MAX_PROTOTYPES,
) -> list[dict[str, Any]]:
    if target_docs_per_group < 1:
        raise ValueError("target_docs_per_group must be >= 1")
    cleaned = [strip_scoring_fields(d) for d in docs]
    if not cleaned:
        return []
    tokenized = [tokenize(document_text(d, text_fields)) for d in cleaned]
    idf = _idf(tokenized)
    vectors = [_sparse_tfidf(toks, idf) for toks in tokenized]
    neighborhoods = _recursive_split(
        list(range(len(cleaned))),
        tokenized,
        idf,
        target=max(target_docs_per_group * max_prototypes, target_docs_per_group),
        path=(),
    )
    leaves: list[tuple[list[int], tuple[str, ...], list[str]]] = []
    for idxs, path in neighborhoods:
        parts = _medoid_partition(idxs, vectors, target_docs_per_group, max_prototypes)
        parent_terms = _top_terms_for_indices(idxs, tokenized, idf, k=8)
        for part in parts:
            contrast = _contrast_terms(part, idxs, tokenized, idf)
            leaves.append((part, path, contrast or parent_terms[:6]))

    if len(leaves) > MAX_GROUPS:
        leaves = _merge_smallest(leaves, MAX_GROUPS)

    groups: list[dict[str, Any]] = []
    for part_i, (idxs, path, contrast) in enumerate(leaves):
        sibling_terms = _sibling_negative_terms(part_i, leaves, tokenized, idf)
        groups.append(
            _group_payload(
                tenant_id=tenant_id,
                collection=collection,
                path=path,
                proto_index=part_i,
                docs=[cleaned[i] for i in idxs],
                token_lists=[tokenized[i] for i in idxs],
                contrast=contrast,
                negatives=sibling_terms,
                idf=idf,
            )
        )
    groups.sort(key=lambda g: g["key"])
    return groups


def summarize_semantic_group(
    *,
    name: str,
    count: int,
    contrast: list[str],
    negatives: list[str],
    entities: list[str],
    examples: list[str],
    attributes: list[str],
) -> str:
    dist = ", ".join(contrast[:10]) or "mixed operational language"
    not_s = ", ".join(negatives[:8]) or "no close sibling contrast"
    ent = ", ".join(entities[:24]) or "no dominant entity"
    attrs = ", ".join(attributes[:8])
    ex = " || ".join(examples[:3]) or "no example excerpt"
    text = (
        f"Semantic neighborhood of {count} records named '{name}'. "
        f"Distinguishing attributes: {dist}. "
        f"Unlike neighboring groups that emphasize: {not_s}. "
        f"Entities: {ent}. "
        f"{'Record attributes: ' + attrs + '. ' if attrs else ''}"
        f"Representative examples: {ex}."
    )
    if len(text) > MAX_SUMMARY_CHARS:
        return text[: MAX_SUMMARY_CHARS - 1] + "…"
    return text


def _idf(tokenized: Sequence[Sequence[str]]) -> dict[str, float]:
    df: Counter[str] = Counter()
    for toks in tokenized:
        df.update(set(toks))
    n = max(len(tokenized), 1)
    return {term: math.log((n + 1) / (count + 1)) + 1.0 for term, count in df.items()}


def _sparse_tfidf(tokens: Sequence[str], idf: dict[str, float]) -> dict[str, float]:
    if not tokens:
        return {}
    tf = Counter(tokens)
    length = len(tokens)
    vec = {t: (c / length) * idf.get(t, 0.0) for t, c in tf.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def _recursive_split(
    indices: list[int],
    tokenized: list[list[str]],
    idf: dict[str, float],
    *,
    target: int,
    path: tuple[str, ...],
    depth: int = 0,
) -> list[tuple[list[int], tuple[str, ...]]]:
    if len(indices) <= target or depth >= 12:
        return [(indices, path)]
    term = _best_split_term(indices, tokenized, idf)
    if term is None:
        return [(indices, path)]
    left = [i for i in indices if term in tokenized[i]]
    right = [i for i in indices if term not in tokenized[i]]
    if min(len(left), len(right)) < MIN_SIDE:
        return [(indices, path)]
    return _recursive_split(
        left, tokenized, idf, target=target, path=path + (term,), depth=depth + 1
    ) + _recursive_split(
        right, tokenized, idf, target=target, path=path + (f"no-{term}",), depth=depth + 1
    )


def _best_split_term(
    indices: list[int],
    tokenized: list[list[str]],
    idf: dict[str, float],
) -> str | None:
    n = len(indices)
    if n < MIN_SIDE * 2:
        return None
    df: Counter[str] = Counter()
    for i in indices:
        df.update(set(tokenized[i]))
    lo = max(MIN_SIDE, int(n * MIN_SPLIT_FRAC))
    hi = min(n - MIN_SIDE, int(n * MAX_SPLIT_FRAC))
    best: tuple[float, str] | None = None
    for term, count in df.items():
        if count < lo or count > hi:
            continue
        # Balanced distinctive split: rare globally, mixed locally.
        score = count * (n - count) * idf.get(term, 0.0)
        if best is None or score > best[0] or (score == best[0] and term < best[1]):
            best = (score, term)
    return None if best is None else best[1]


def _medoid_partition(
    indices: list[int],
    vectors: list[dict[str, float]],
    target: int,
    max_prototypes: int,
) -> list[list[int]]:
    n = len(indices)
    if n <= target or max_prototypes <= 1:
        return [indices]
    k = min(max_prototypes, max(2, math.ceil(n / target)))
    if k <= 1:
        return [indices]
    medoids = _farthest_medoids(indices, vectors, k)
    buckets: list[list[int]] = [[] for _ in range(len(medoids))]
    for i in indices:
        best_j = 0
        best_s = -1.0
        for j, m in enumerate(medoids):
            s = _cosine(vectors[i], vectors[m])
            if s > best_s or (s == best_s and j < best_j):
                best_s = s
                best_j = j
        buckets[best_j].append(i)
    return [b for b in buckets if b]


def _farthest_medoids(
    indices: list[int], vectors: list[dict[str, float]], k: int
) -> list[int]:
    ordered = sorted(indices)
    picked = [ordered[0]]
    while len(picked) < k and len(picked) < len(ordered):
        best_i = ordered[0]
        best_d = -1.0
        for i in ordered:
            if i in picked:
                continue
            d = min(1.0 - _cosine(vectors[i], vectors[m]) for m in picked)
            if d > best_d or (d == best_d and i < best_i):
                best_d = d
                best_i = i
        picked.append(best_i)
    return picked


def _top_terms_for_indices(
    indices: Sequence[int],
    tokenized: list[list[str]],
    idf: dict[str, float],
    k: int,
) -> list[str]:
    tf: Counter[str] = Counter()
    for i in indices:
        tf.update(tokenized[i])
    length = max(sum(tf.values()), 1)
    ranked = sorted(
        tf.keys(),
        key=lambda t: (-(tf[t] / length) * idf.get(t, 0.0), t),
    )
    return ranked[:k]


def _contrast_terms(
    part: Sequence[int],
    parent: Sequence[int],
    tokenized: list[list[str]],
    idf: dict[str, float],
) -> list[str]:
    part_set = set(part)
    tf_part: Counter[str] = Counter()
    tf_rest: Counter[str] = Counter()
    for i in parent:
        bag = set(tokenized[i])
        if i in part_set:
            tf_part.update(bag)
        else:
            tf_rest.update(bag)
    n_part = max(len(part), 1)
    n_rest = max(len(parent) - len(part), 1)
    scored: list[tuple[float, str]] = []
    for term, c in tf_part.items():
        frac = c / n_part
        other = tf_rest.get(term, 0) / n_rest
        lift = frac / (other + 0.02)
        scored.append((lift * frac * idf.get(term, 1.0), term))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, t in scored[:10] if _ > 1.15]


def _sibling_negative_terms(
    idx: int,
    leaves: list[tuple[list[int], tuple[str, ...], list[str]]],
    tokenized: list[list[str]],
    idf: dict[str, float],
) -> list[str]:
    mine = set(leaves[idx][2])
    others: Counter[str] = Counter()
    for j, (_idxs, _path, contrast) in enumerate(leaves):
        if j == idx:
            continue
        others.update(contrast[:6])
    ranked = [t for t, _ in others.most_common(12) if t not in mine]
    if ranked:
        return ranked[:8]
    # Fall back to terms frequent in a nearby leaf.
    if len(leaves) == 1:
        return []
    other = leaves[(idx + 1) % len(leaves)][0]
    return _top_terms_for_indices(other, tokenized, idf, k=6)


def _merge_smallest(
    leaves: list[tuple[list[int], tuple[str, ...], list[str]]],
    cap: int,
) -> list[tuple[list[int], tuple[str, ...], list[str]]]:
    items = list(leaves)
    while len(items) > cap:
        items.sort(key=lambda x: (len(x[0]), x[1]))
        a = items.pop(0)
        b = items.pop(0)
        items.append((a[0] + b[0], a[1] or b[1], list(dict.fromkeys(a[2] + b[2]))))
    return items


def _example_snippet(doc: dict[str, Any]) -> str:
    title = str(doc.get("title") or "").strip()
    desc = str(doc.get("description") or "").replace("\n", " ").strip()
    # Keep the distinctive lead-in; drop the repeated operator boilerplate if present.
    cut = desc.find("The on-call engineer")
    if cut > 40:
        desc = desc[:cut].strip()
    desc = desc[:EXAMPLE_CHARS].rstrip(" .")
    blob = f"{title}: {desc}" if desc else title
    return blob[: EXAMPLE_CHARS + 80]


def _group_payload(
    *,
    tenant_id: str,
    collection: str,
    path: tuple[str, ...],
    proto_index: int,
    docs: list[dict[str, Any]],
    token_lists: list[list[str]],
    contrast: list[str],
    negatives: list[str],
    idf: dict[str, float],
) -> dict[str, Any]:
    ids = [str(d["_id"]) for d in docs]
    entities = sorted({str(d.get("customer_id")) for d in docs if d.get("customer_id")})
    times = [d.get("timestamp") for d in docs if isinstance(d.get("timestamp"), datetime)]
    areas = sorted({str(d.get("product_area")) for d in docs if d.get("product_area")})
    sevs = sorted({str(d.get("severity")) for d in docs if d.get("severity")})
    attributes = [a for a in areas + sevs if a]
    # Rank member docs by how well they match contrast terms; those become examples.
    ranked_docs = sorted(
        docs,
        key=lambda d: (
            -sum(1 for t in contrast[:8] if t in set(tokenize(document_text(d)))),
            str(d.get("_id")),
        ),
    )
    examples = [_example_snippet(d) for d in ranked_docs[:3]]
    path_s = "-".join(path[:6]) if path else "root"
    key = f"sem:{path_s}:p{proto_index}"
    label_terms = contrast[:4] or path[:4] or ["mixed"]
    name = f"{collection} {' '.join(label_terms)}"
    member_terms = _top_terms_for_indices(
        list(range(len(token_lists))),
        token_lists,
        idf,
        k=8,
    )
    extra = list(
        dict.fromkeys(
            contrast + list(path) + member_terms + entities[:40] + attributes + examples
        )
    )
    tmin = min(times) if times else None
    tmax = max(times) if times else None
    summary = summarize_semantic_group(
        name=name,
        count=len(ids),
        contrast=contrast,
        negatives=negatives,
        entities=entities,
        examples=examples,
        attributes=attributes,
    )
    return {
        "key": key,
        "name": name,
        "filter": {"tenant_id": tenant_id, "_id": {"$in": ids}},
        "document_ids": ids,
        "document_count": len(ids),
        "time_min": tmin,
        "time_max": tmax,
        "entities": entities[:40],
        "topics": contrast[:12],
        "extra_terms": extra,
        "examples": examples,
        "distinguishing": contrast,
        "summary": summary,
    }
