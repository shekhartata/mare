"""Deterministic text-heavy corpus for the scale / vector-efficiency benchmark.

Gold evidence lives in the first SCALE_GOLD_PREFIX documents. Larger slices only
add distractors. Grouping must never read ``topic_id``; that field is a scoring
label only.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.constants import DEFAULT_TENANT, SCALE_GOLD_PREFIX, SCALE_RAW_DB

SCALE_COLLECTION = "incidents"
TEXT_FIELDS = ("title", "description", "resolution")
FORBIDDEN_GROUPING_FIELDS = frozenset({"topic_id", "tier", "family", "query_lexicon"})

BOILERPLATE = (
    "The on-call engineer captured timestamps from the operator console and attached "
    "them to this record so later reviews can reconstruct the window. Watchers were "
    "paged according to the existing escalation policy. A short bridge was opened "
    "with the account team. No customer-identifying payload is copied into this "
    "narrative; identifiers live in metadata fields. Follow-up work is tracked in "
    "the linked ticket queue. The write-up below is intentionally long so retrieval "
    "has enough natural language to rank against, rather than a one-line error code. "
    "Operators also noted dashboard lag, overlapping alerts, and a backlog of similar "
    "pages from the same region during the same shift. Secondary checks included "
    "recent config diffs, feature-flag flips, and whether a deploy landed in the "
    "hour before symptoms. None of those checks replace the specific cause named "
    "in the resolution. "
)


@dataclass(frozen=True)
class Topic:
    topic_id: str
    family: str
    tier: str  # common | medium | rare
    title: str
    doc_phrases: tuple[str, ...]
    query_phrases: tuple[str, ...]
    product_area: str


def _t(
    topic_id: str,
    family: str,
    tier: str,
    title: str,
    docs: tuple[str, ...],
    queries: tuple[str, ...],
    area: str,
) -> Topic:
    return Topic(topic_id, family, tier, title, docs, queries, area)


TOPICS: tuple[Topic, ...] = (
    _t(
        "expired_token",
        "token_auth",
        "common",
        "Access credential lifetime elapsed mid-request",
        (
            "ACCESS_TOKEN_TTL_SEC elapsed before the worker finished",
            "session cookie max-age ended while the operator was idle",
            "short-lived bearer credential timed out during a long export",
        ),
        (
            "sign-in material stopped being accepted after it outlived its lifetime",
            "jobs died because the granted lifetime was shorter than the work window",
        ),
        "identity",
    ),
    _t(
        "invalid_issuer",
        "token_auth",
        "common",
        "Assertion host did not match the configured identity origin",
        (
            "AUTH_ISSUER still pointed at auth-v2 after the cutover to auth-v3",
            "jwt iss claim expected https://auth-v3.example.test but received v2",
            "OIDC issuer URL in the runtime map was stale",
        ),
        (
            "identity origin hostname inside the assertion disagreed with config",
            "relying parties still trusted the previous identity host",
        ),
        "identity",
    ),
    _t(
        "invalid_audience",
        "token_auth",
        "medium",
        "Assertion was minted for a different resource identifier",
        (
            "jwt aud claim listed billing-api but the caller hit inventory-api",
            "resource identifier in the assertion did not match the intended audience",
            "authorized party azp was bound to the wrong service name",
        ),
        (
            "credential was minted for a different API than the one being called",
            "the intended recipient named in the assertion was not this service",
        ),
        "identity",
    ),
    _t(
        "certificate_expiry",
        "token_auth",
        "medium",
        "Mutual TLS material was past notAfter",
        (
            "mTLS client certificate notAfter had passed at 2024-05-01",
            "leaf cert serial 8f2a expired and handshakes started failing",
            "certificate rotation job did not replace the file on disk",
        ),
        (
            "encrypted channel identity documents were past their validity date",
            "handshake failed because the signed public key material was too old",
        ),
        "identity",
    ),
    _t(
        "missing_credentials",
        "token_auth",
        "common",
        "Caller sent no authorization material",
        (
            "Authorization header was empty on the inbound request",
            "API key environment variable was unset in the worker",
            "service account key file path pointed at a missing secret",
        ),
        (
            "the caller omitted the secret that gateways require",
            "no proof of identity was attached to the request at all",
        ),
        "identity",
    ),
    _t(
        "billing_webhook_404",
        "billing",
        "common",
        "Invoice hook posted to a retired path",
        (
            "POST /billing/v1 returned HTTP 404 webhook_not_found",
            "billing-worker still called the retired v1 hook URL",
            "hooks.northstar.test/billing/v1 was removed after billing-4.0",
        ),
        (
            "payment notices were delivered to an address that no longer exists",
            "the old callback path answered that the route was gone",
        ),
        "billing",
    ),
    _t(
        "invoice_mismatch",
        "billing",
        "medium",
        "Line items did not sum to the charged total",
        (
            "invoice subtotal and tax did not equal the captured amount",
            "proration on mid-cycle seat changes double-counted a line",
            "currency conversion used yesterday's rate on a same-day charge",
        ),
        (
            "the billed figure disagreed with the itemized list",
            "seat changes were priced twice in the same period",
        ),
        "billing",
    ),
    _t(
        "payment_retry",
        "billing",
        "common",
        "Card network declined then later captured twice",
        (
            "processor returned do_not_honor then a delayed capture succeeded",
            "idempotency key was reused across two capture attempts",
            "customer saw a duplicate charge after an automatic retry",
        ),
        (
            "the card network bounced the first try and a later try stuck twice",
            "a replay of the capture request billed the same order again",
        ),
        "billing",
    ),
    _t(
        "rate_limit_429",
        "traffic",
        "common",
        "Partner burst tripped the per-minute quota",
        (
            "HTTP 429 from api-gateway after 600 requests in one minute",
            "Retry-After advertised 45 seconds on the partner integration",
            "token bucket for tenant burst class emptied during a backfill",
        ),
        (
            "the partner sent more calls in a minute than the quota allows",
            "the edge asked the client to wait before sending more work",
        ),
        "platform",
    ),
    _t(
        "cache_stampede",
        "traffic",
        "medium",
        "Hot key expiry caused a thundering herd",
        (
            "redis key catalog:hot expired and every pod rebuilt the blob",
            "singleflight was not wrapping the catalog fetch",
            "origin database CPU spiked while the cache was empty",
        ),
        (
            "a popular entry vanished and every replica rebuilt it at once",
            "the backing store was stampeded after a popular key disappeared",
        ),
        "platform",
    ),
    _t(
        "disk_full",
        "infra",
        "medium",
        "Log volume filled the data disk",
        (
            "filesystem on /var/lib/app reported 100% inodes on nvme0n1",
            "wal writer stopped with ENOSPC during peak ingest",
            "log rotation retained 30 days instead of 7",
        ),
        (
            "the machine ran out of space to append more records",
            "writers halted because the volume had no room left",
        ),
        "platform",
    ),
    _t(
        "memory_leak",
        "infra",
        "medium",
        "Heap grew without bound in the renderer",
        (
            "rss for pdf-renderer climbed to 14GiB over eight hours",
            "pprof showed unbounded accumulation in the font cache",
            "OOMKiller SIGKILL after the cgroup memory.max was hit",
        ),
        (
            "resident size kept climbing until the supervisor killed the process",
            "a cache inside the process never released what it allocated",
        ),
        "platform",
    ),
    _t(
        "slow_query",
        "data",
        "common",
        "Unindexed filter scanned the incidents collection",
        (
            "explain showed COLLSCAN on opened_at plus a regex on summary",
            "query planner picked the wrong index after a statistics refresh",
            "p99 of find on incidents jumped from 12ms to 2.4s",
        ),
        (
            "a lookup walked every record because no supporting index existed",
            "the planner chose a wide scan after statistics went stale",
        ),
        "data",
    ),
    _t(
        "replica_lag",
        "data",
        "medium",
        "Secondary was minutes behind the primary",
        (
            "replication lag on rs0-2 reached 240 seconds",
            "readPreference secondary returned pre-cutover documents",
            "oplog window was too small for the catch-up",
        ),
        (
            "a follower had not applied the leader's writes for minutes",
            "reads aimed at a follower saw a world that was already obsolete",
        ),
        "data",
    ),
    _t(
        "tls_handshake",
        "network",
        "common",
        "Handshake aborted on protocol mismatch",
        (
            "client offered only TLS1.1 while the edge required 1.2+",
            "ALPN negotiation failed between envoy and the upstream",
            "cipher suite mismatch after the security baseline tightened",
        ),
        (
            "the encrypted greeting failed because both sides spoke different versions",
            "protocol names could not be agreed during the opening exchange",
        ),
        "network",
    ),
    _t(
        "dns_resolution",
        "network",
        "medium",
        "Service hostname stopped resolving",
        (
            "NXDOMAIN for payments.internal.example.test from CoreDNS",
            "stale cluster IP remained in the node resolver cache",
            "SRV record for the headless service was deleted during a chart bump",
        ),
        (
            "the internal name no longer mapped to an address",
            "nodes kept a vanished mapping in their local resolver",
        ),
        "network",
    ),
    _t(
        "queue_backlog",
        "async",
        "common",
        "Work queue depth exceeded the drain rate",
        (
            "sqs ApproximateNumberOfMessages hit 180000",
            "consumer concurrency was pinned at 2 after a bad deploy",
            "visibility timeout expired and the same payload retried forever",
        ),
        (
            "queued work piled up faster than workers could finish it",
            "the same payload kept returning because the hide window was too short",
        ),
        "platform",
    ),
    _t(
        "kafka_consumer_lag",
        "async",
        "rare",
        "Consumer group fell behind a compacted topic",
        (
            "consumer group billing.ledger lag on topic events.v2 reached 9e6",
            "max.poll.interval.ms was exceeded and the member was kicked",
            "compaction dropped keys the projector still expected",
        ),
        (
            "the projector trailed a compacted stream by millions of records",
            "the member was ejected for taking too long between polls",
        ),
        "data",
    ),
    _t(
        "s3_permission",
        "storage",
        "medium",
        "Object store denied the new role",
        (
            "AccessDenied on s3:GetObject for bucket customer-exports",
            "bucket policy no longer allowed the irsa role after a rename",
            "KMS key policy omitted the new task role",
        ),
        (
            "the object store refused the renamed role",
            "the wrapping key would not unwrap for the new task identity",
        ),
        "storage",
    ),
    _t(
        "iam_role_denied",
        "storage",
        "rare",
        "AssumeRole was rejected after an org SCP change",
        (
            "AccessDenied on sts:AssumeRole for role/prod-exporter",
            "organization SCP blocked ec2:CreateTags in that account",
            "permission boundary on the deployer role was tightened",
        ),
        (
            "the account-wide guardrail blocked the role switch",
            "a new permission boundary stopped the deployer from tagging",
        ),
        "storage",
    ),
    _t(
        "feature_flag_dark",
        "app",
        "common",
        "Dark launch served the new checkout to everyone",
        (
            "flag checkout_v2 targeting rule was inverted in prod",
            "percentage rollout jumped from 1 to 100 after a YAML indent bug",
            "default variation flipped when the SDK could not reach the relay",
        ),
        (
            "an unfinished storefront path was shown to the whole population",
            "a targeting rule was inverted so the new path became the default",
        ),
        "app",
    ),
    _t(
        "schema_migration",
        "data",
        "medium",
        "Expand-contract migration dropped a still-read column",
        (
            "ALTER TABLE dropped column legacy_plan_code while readers still selected it",
            "expand-contract step 2 ran before the last reader was bounced",
            "ORM mapping still referenced the removed attribute",
        ),
        (
            "a column still queried by old readers was removed too early",
            "the mapping layer kept asking for an attribute that no longer exists",
        ),
        "data",
    ),
    _t(
        "timezone_bug",
        "app",
        "rare",
        "DST shift double-counted a daily job",
        (
            "cron used local time and fired twice during the fall-back hour",
            "timestamp stored as local wall time was interpreted as UTC",
            "report window skipped an hour after spring-forward",
        ),
        (
            "a clock change made a daily job run twice in one night",
            "local wall time was treated as if it were a universal clock",
        ),
        "app",
    ),
    _t(
        "pagination_off_by_one",
        "app",
        "rare",
        "List endpoint skipped the first row of page two",
        (
            "offset pagination used skip = page * limit instead of (page-1)*limit",
            "clients lost the first row of every subsequent page",
            "cursor based on created_at collided for rows in the same millisecond",
        ),
        (
            "the second page of a list omitted its first row",
            "two rows sharing a timestamp confused the cursor",
        ),
        "app",
    ),
    _t(
        "csrf_token",
        "security",
        "medium",
        "State-changing form lacked a synchronizer token",
        (
            "POST /settings/billing had no synchronizer token check",
            "SameSite=None cookie was sent on a cross-site form post",
            "double-submit cookie pattern was not implemented on that route",
        ),
        (
            "a cross-site form could change billing because no synchronizer was checked",
            "a cookie marked for cross-site use rode along on a forged post",
        ),
        "security",
    ),
    _t(
        "cors_block",
        "security",
        "common",
        "Browser preflight was missing the new origin",
        (
            "Access-Control-Allow-Origin did not include app.example.test",
            "preflight OPTIONS lacked Access-Control-Allow-Headers authorization",
            "wildcard origin was rejected because credentials were true",
        ),
        (
            "the browser blocked a call because the new origin was not listed",
            "a credentialed request cannot use a wildcard allowed origin",
        ),
        "security",
    ),
    _t(
        "websocket_drop",
        "network",
        "rare",
        "Idle sockets were closed by a new idle timeout",
        (
            "load balancer idle timeout of 60s closed the websocket",
            "client did not send ping frames on the negotiated interval",
            "sticky session cookie was missing so reconnects hit another pod",
        ),
        (
            "long-lived sockets died because the proxy idle window was too short",
            "reconnects landed on a different replica without affinity",
        ),
        "network",
    ),
    _t(
        "graphql_n_plus_one",
        "app",
        "rare",
        "Resolver issued a query per nested node",
        (
            "dataloader was not wrapping the user lookup in the comments field",
            "one page of 50 tickets caused 50 extra SQL round trips",
            "APM showed N+1 under graphql.comments.author",
        ),
        (
            "each nested node triggered its own round trip to the database",
            "a list of fifty items became fifty extra lookups",
        ),
        "app",
    ),
    _t(
        "redis_eviction",
        "infra",
        "rare",
        "volatile-lru evicted session keys under pressure",
        (
            "maxmemory-policy volatile-lru dropped session:* keys",
            "used_memory_human crossed maxmemory during a scan",
            "operators were signed out because their session hashes vanished",
        ),
        (
            "a memory cap under pressure deleted live session hashes",
            "people were signed out because their session entries disappeared",
        ),
        "platform",
    ),
    _t(
        "connection_pool_exhaust",
        "infra",
        "common",
        "Pool waiters piled up behind leaked connections",
        (
            "HikariPool-1 timeout after 30s waiting for a connection",
            "leaked connections were held across an awaited HTTP call",
            "pool size 10 was too small for the new fan-out",
        ),
        (
            "threads stalled because every database handle was already checked out",
            "handles were held across an outbound call and never returned",
        ),
        "platform",
    ),
    _t(
        "clock_skew",
        "infra",
        "rare",
        "Node clock drifted and signed requests failed",
        (
            "ntpd was disabled and the node drifted 12 minutes fast",
            "SigV4 signatures were rejected as expired",
            "JWT nbf failed because the worker clock was ahead",
        ),
        (
            "the machine's clock ran fast enough that signed calls looked expired",
            "not-before checks failed because the worker believed it was later",
        ),
        "platform",
    ),
    _t(
        "locale_encoding",
        "app",
        "rare",
        "CSV export used Latin-1 on UTF-8 names",
        (
            "export wrote ISO-8859-1 while names were UTF-8",
            "mojibake appeared for accented account manager names",
            "Excel opened the file with a Windows code page",
        ),
        (
            "exported names were decoded with the wrong character set",
            "accented names became garbled in the spreadsheet",
        ),
        "app",
    ),
    _t(
        "pdf_render",
        "app",
        "rare",
        "Invoice PDF hung on an embedded font",
        (
            "weasyprint hung on a missing @font-face url",
            "PDF generation workers filled the queue behind one blocked job",
            "fallback font metrics made tables overflow the page box",
        ),
        (
            "a missing typeface URL blocked the invoice renderer",
            "one stuck render job stopped the rest of the PDF workers",
        ),
        "app",
    ),
    _t(
        "image_exif",
        "app",
        "rare",
        "Uploader stripped GPS but left orientation",
        (
            "exiftool stripped GPS tags but left Orientation=6",
            "thumbnails rendered sideways after the strip job",
            "content-type sniffing treated HEIC as JPEG",
        ),
        (
            "location tags were removed but rotation metadata remained",
            "previews appeared on their side after the strip job",
        ),
        "app",
    ),
    _t(
        "search_synonym",
        "search",
        "rare",
        "Synonym graph expanded a query into noise",
        (
            "Atlas Search synonym mapping turned 'bill' into 40 terms",
            "query exploded past the clause limit and returned empty",
            "operators could not find known invoices by a short nickname",
        ),
        (
            "a short nickname expanded into so many terms the search died",
            "the synonym graph made a simple lookup return nothing",
        ),
        "search",
    ),
    _t(
        "webhook_signature",
        "security",
        "medium",
        "Partner signed with a rotated secret we still rejected",
        (
            "HMAC-SHA256 of the body used signing secret v3 while we verified v2",
            "timestamp header was outside the five-minute skew window",
            "signature version header sv2 was ignored",
        ),
        (
            "we verified a partner callback with the previous shared secret",
            "the timestamp on the callback sat outside the allowed skew",
        ),
        "security",
    ),
    _t(
        "oauth_state_mismatch",
        "identity",
        "rare",
        "Login callback state cookie did not match",
        (
            "oauth state parameter did not match the HttpOnly cookie",
            "load balancer affinity lost the state cookie on the callback",
            "login started on pod A and finished on pod B without shared store",
        ),
        (
            "the round-trip proof on the login callback did not match what was stored",
            "the handshake started on one replica and finished on another",
        ),
        "identity",
    ),
    _t(
        "session_fixation",
        "security",
        "rare",
        "Session identifier was not rotated after login",
        (
            "session id issued pre-login was reused after password success",
            "cookie was not regenerated in the auth callback",
            "an attacker-supplied session id remained valid",
        ),
        (
            "the identifier from before login was still accepted afterwards",
            "a value an attacker could pick stayed valid through sign-in",
        ),
        "security",
    ),
    _t(
        "cookie_samesite",
        "security",
        "medium",
        "Embedded checkout lost its session cookie",
        (
            "SameSite=Lax blocked the cookie on a POST from the embedder",
            "third-party iframe checkout needed SameSite=None; Secure",
            "Chrome partitioned the cookie after the CHIPS rollout",
        ),
        (
            "an embedded checkout stopped receiving its session cookie",
            "a cross-site POST no longer carried the lax cookie",
        ),
        "security",
    ),
    _t(
        "hsts_preload",
        "network",
        "rare",
        "HTTP health check broke after HSTS preload",
        (
            "HSTS preload submitted for example.test including subdomains",
            "HTTP :80 health check started being upgraded and failing",
            "load balancer health target still used http://",
        ),
        (
            "plain HTTP probes failed after the domain was locked to HTTPS",
            "the health target still spoke unencrypted on port 80",
        ),
        "network",
    ),
    _t(
        "healthcheck_flap",
        "infra",
        "common",
        "Shallow probe passed while the dependency was down",
        (
            "readiness probe only hit /healthz and ignored mongo",
            "pods stayed Ready while the database failover was in progress",
            "kubelet never restarted the process that was hung on a lock",
        ),
        (
            "the shallow probe stayed green while a dependency was actually down",
            "the process hung on a lock but still looked ready",
        ),
        "platform",
    ),
)

assert len(TOPICS) >= 40
assert all(t.tier in {"common", "medium", "rare"} for t in TOPICS)

_BY_ID = {t.topic_id: t for t in TOPICS}


def customer_count_for(n_docs: int) -> int:
    return max(50, n_docs // 40)


def topic_weights() -> list[float]:
    weights = []
    for t in TOPICS:
        if t.tier == "rare":
            weights.append(0.004)
        elif t.tier == "medium":
            weights.append(0.018)
        else:
            weights.append(0.0)
    rare_medium = sum(weights)
    n_common = sum(1 for t in TOPICS if t.tier == "common")
    common_w = (1.0 - rare_medium) / n_common
    return [common_w if t.tier == "common" else w for t, w in zip(TOPICS, weights, strict=True)]


def incident_id(seq: int) -> str:
    return f"inc_scale_{seq:06d}"


def customer_id(index: int) -> str:
    return f"cust_scale_{index:04d}"


def generate_scale_corpus(
    n: int = 100_000,
    *,
    seed: int = 7,
    tenant_id: str = DEFAULT_TENANT,
    gold_prefix: int | None = None,
) -> dict[str, Any]:
    rng = random.Random(seed)
    gold_n = min(n, SCALE_GOLD_PREFIX if gold_prefix is None else gold_prefix)
    rng = random.Random(seed)
    n_customers = customer_count_for(n)
    weights = topic_weights()
    start = datetime(2024, 1, 1, 8, 0, 0)
    docs: list[dict[str, Any]] = []
    for seq in range(n):
        topic = rng.choices(TOPICS, weights=weights, k=1)[0]
        cid = customer_id(seq % n_customers)
        ts = start + timedelta(minutes=rng.randint(0, 60 * 24 * 200))
        phrase = rng.choice(topic.doc_phrases)
        extra = rng.choice(topic.doc_phrases)
        title = f"{topic.title} ({cid})"
        description = (
            f"{phrase}. {BOILERPLATE} "
            f"Product area {topic.product_area}. Related note: {extra}. "
            f"Opened for {cid} during the {ts.strftime('%B %Y')} window."
        )
        resolution = (
            f"Mitigation focused on {phrase.lower()}. {BOILERPLATE} "
            f"Confirm the {topic.product_area} path no longer reproduces. "
            f"Do not confuse this with neighboring {topic.family} failures."
        )
        docs.append(
            {
                "_id": incident_id(seq),
                "tenant_id": tenant_id,
                "customer_id": cid,
                "seq": seq,
                "timestamp": ts,
                "title": title,
                "description": description,
                "resolution": resolution,
                "product_area": topic.product_area,
                "severity": rng.choice(["sev-1", "sev-2", "sev-3", "sev-4"]),
                "status": rng.choice(["open", "mitigated", "resolved"]),
                "metadata": {
                    "family": topic.family,
                    "region": rng.choice(["us-east-1", "eu-west-1", "ap-south-1"]),
                },
                "topic_id": topic.topic_id,
                "tier": topic.tier,
                "family": topic.family,
            }
        )
        _pad_text(docs[-1], rng)
    queries = _build_queries(docs, random.Random(seed + 99), gold_n)
    return {
        "database": SCALE_RAW_DB,
        "collection": SCALE_COLLECTION,
        "documents": docs,
        "queries": queries,
        "n_customers": n_customers,
        "n_topics": len(TOPICS),
        "gold_prefix": gold_n,
    }


def write_scale_gold(queries: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "gold_prefix": SCALE_GOLD_PREFIX,
            "n_queries": len(queries),
            "split": {"dev": sum(1 for q in queries if q["split"] == "dev"),
                      "heldout": sum(1 for q in queries if q["split"] == "heldout")},
        },
        "queries": queries,
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")


def grouping_projection() -> dict[str, int]:
    """Fields a grouping pass is allowed to read. Excludes scoring labels."""
    return {
        "_id": 1,
        "tenant_id": 1,
        "customer_id": 1,
        "seq": 1,
        "timestamp": 1,
        "title": 1,
        "description": 1,
        "resolution": 1,
        "product_area": 1,
        "severity": 1,
        "status": 1,
        "metadata": 1,
    }


def _pad_text(doc: dict[str, Any], rng: random.Random) -> None:
    target = rng.randint(1200, 2000)
    blob = f"{doc['title']} {doc['description']} {doc['resolution']}"
    while len(blob) < target:
        doc["description"] += " " + BOILERPLATE
        blob = f"{doc['title']} {doc['description']} {doc['resolution']}"


def _build_queries(
    docs: list[dict[str, Any]], rng: random.Random, gold_prefix: int
) -> list[dict[str, Any]]:
    prefix = [d for d in docs if int(d["seq"]) < gold_prefix]
    by_topic: dict[str, list[dict[str, Any]]] = {t.topic_id: [] for t in TOPICS}
    for d in prefix:
        by_topic[d["topic_id"]].append(d)
    queries: list[dict[str, Any]] = []

    def add(category: str, topic: Topic, question: str, gold: list[dict[str, Any]]) -> None:
        ids = [str(d["_id"]) for d in gold]
        if len(ids) < 2:
            return
        queries.append(
            {
                "query_id": f"Q{len(queries) + 1:03d}",
                "question": question,
                "gold_document_ids": ids,
                "category": category,
                "tier": topic.tier,
                "topic_id": topic.topic_id,
                "family": topic.family,
                "split": "pending",
            }
        )

    # Q1 direct semantic — question may use document phrasing.
    for topic in TOPICS:
        pool = by_topic[topic.topic_id]
        if len(pool) < 4:
            continue
        gold = pool[: min(12, len(pool))]
        add(
            "direct_semantic",
            topic,
            f"Find incidents involving {topic.doc_phrases[0]}.",
            gold,
        )
        if len(topic.doc_phrases) > 1:
            add(
                "direct_semantic",
                topic,
                f"Retrieve records that mention {topic.doc_phrases[1]}.",
                gold,
            )

    # Q2 paraphrase — question uses only query_phrases, not doc_phrases.
    for topic in TOPICS:
        pool = by_topic[topic.topic_id]
        if len(pool) < 4:
            continue
        gold = pool[: min(12, len(pool))]
        add(
            "paraphrase",
            topic,
            f"Find incidents where {topic.query_phrases[0]}.",
            gold,
        )
        if len(topic.query_phrases) > 1:
            add(
                "paraphrase",
                topic,
                f"Which records show that {topic.query_phrases[1]}?",
                gold,
            )

    # Q3 fine-grained — one sibling in token_auth / billing / security.
    for family in ("token_auth", "billing", "security"):
        members = [t for t in TOPICS if t.family == family]
        for topic in members:
            pool = by_topic[topic.topic_id]
            if len(pool) < 3:
                continue
            add(
                "fine_grained",
                topic,
                f"Find incidents whose cause is specifically {topic.title.lower()}, "
                f"not other {family} failures.",
                pool[: min(10, len(pool))],
            )

    # Q4 rare topics.
    for topic in TOPICS:
        if topic.tier != "rare":
            continue
        pool = by_topic[topic.topic_id]
        if len(pool) < 2:
            continue
        add(
            "rare",
            topic,
            f"Find the uncommon incidents about {topic.query_phrases[0]}.",
            pool[: min(8, len(pool))],
        )
        if len(pool) >= 4:
            add(
                "rare",
                topic,
                f"Retrieve records for {topic.title.lower()}.",
                pool[: min(8, len(pool))],
            )

    # Q5 similar distractors — gold is one customer's slice of a common topic.
    common = [t for t in TOPICS if t.tier == "common"]
    customers = sorted({d["customer_id"] for d in prefix})
    rng.shuffle(customers)
    for i, cid in enumerate(customers[:40]):
        topic = common[i % len(common)]
        gold = [d for d in prefix if d["customer_id"] == cid and d["topic_id"] == topic.topic_id]
        if len(gold) < 2:
            gold = [d for d in prefix if d["customer_id"] == cid][:6]
        if len(gold) < 2:
            continue
        add(
            "similar_distractors",
            topic,
            f"Find {topic.title.lower()} incidents for {cid} only, "
            "not other customers with similar symptoms.",
            gold,
        )

    rng.shuffle(queries)
    for i, q in enumerate(queries):
        q["query_id"] = f"Q{i + 1:03d}"
        q["split"] = "dev" if (i % 5 == 0) else "heldout"
    return queries
