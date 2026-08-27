"""Deterministic synthetic dataset with gold-labeled multi-hop stories."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.constants import DEFAULT_TENANT, RAW_DB

REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-south-1", "eu-central-1"]
INDUSTRIES = [
    "logistics",
    "fintech",
    "healthcare",
    "retail",
    "media",
    "education",
    "banking",
    "analytics",
    "travel",
    "payments",
]
TIERS = ["starter", "pro", "enterprise"]
SERVICES = ["api-gateway", "auth-service", "billing-worker", "deployer", "scheduler", "storefront"]
ENVIRONMENTS = ["dev", "staging", "prod"]

CUSTOMER_NAMES = [
    "Northwind Labs",
    "Blue Harbor Co",
    "PixelForge",
    "Cedar Systems",
    "Nimbus Retail",
    "Kite Mobile",
    "Apex Logistics",
    "Summit Health",
    "Copperline",
    "Vega Cloud",
    "Ironclad Dev",
    "Northstar Payments",
    "Maple Legal",
    "Brightpath",
    "Cascade Bank",
    "Orchid Bio",
    "Helio Grid",
    "Fable Media",
    "Harbor Health",
    "Quartz Freight",
    "Aster Finance",
    "Redwood Analytics",
    "Nova Dental",
    "Lark Hotels",
    "Pebble Pay",
    "Arcane Studio",
    "Willow Energy",
    "Lumen Education",
    "Cinder Logistics",
    "Boreal Tech",
    "Quilt Retail",
    "Sable Insurance",
    "Mesa Robotics",
    "Ivory Bank",
    "Drift Commerce",
    "Pinecone CRM",
    "Echo Legal",
    "Flint Industrial",
    "Aurora Labs",
    "Cobalt Health",
    "Orbit Media",
    "Tidal Software",
    "Ember Foods",
    "Solstice Travel",
    "Canyon Data",
    "Glacier Pay",
    "Nimbus Farm",
    "Relay Networks",
    "Prism Design",
    "Anchor Shipping",
]


@dataclass
class Story:
    story_id: str
    customer_id: str
    title: str
    gold_answer: str
    questions: list[dict[str, str]]
    gold_sources: list[tuple[str, str]] = field(default_factory=list)


def generate(seed: int = 42) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    customers = _customers(rng)
    stories, extra = _stories(rng)
    tickets = extra["tickets"]
    deployments = extra["deployments"]
    migrations = extra["migrations"]
    incidents = extra["incidents"]
    logs = extra["logs"]

    tickets.extend(_noise_tickets(rng, n=800 - len(tickets)))
    deployments.extend(_noise_deployments(rng, n=400 - len(deployments)))
    migrations.extend(_noise_migrations(rng, n=24 - len(migrations)))
    incidents.extend(_noise_incidents(rng, n=150 - len(incidents)))
    logs.extend(_noise_logs(rng, n=4000 - len(logs)))

    gold = _gold(stories) + _capability_queries(customers, incidents)
    return {
        "customers": customers,
        "tickets": tickets,
        "deployments": deployments,
        "migrations": migrations,
        "incidents": incidents,
        "logs": logs,
        "gold": gold,
        "stories_meta": [
            {"story_id": s.story_id, "customer_id": s.customer_id, "title": s.title} for s in stories
        ],
    }


def write_gold(gold: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"queries": gold}, indent=2, default=str) + "\n")


def _base(**kwargs: Any) -> dict[str, Any]:
    doc = {"tenant_id": DEFAULT_TENANT}
    doc.update(kwargs)
    return doc


def _customers(rng: random.Random) -> list[dict[str, Any]]:
    rows = []
    for i, name in enumerate(CUSTOMER_NAMES, start=1):
        cid = f"cust_{i:03d}"
        created = datetime(2023, 1, 1) + timedelta(days=rng.randint(0, 400))
        rows.append(
            _base(
                _id=cid,
                customer_id=cid,
                name=name,
                subscription_tier=rng.choice(TIERS) if cid not in _STORY_TIERS else _STORY_TIERS[cid],
                region=rng.choice(REGIONS) if cid not in _STORY_REGIONS else _STORY_REGIONS[cid],
                industry=INDUSTRIES[(i - 1) % len(INDUSTRIES)],
                account_manager=rng.choice(
                    ["Priya Shah", "James Okonkwo", "Elena Rossi", "Kenji Sato", "Maya Cohen"]
                ),
                created_at=created,
                feature_flags=_STORY_FLAGS.get(cid, {"checkout_v2": rng.random() > 0.4}),
                status="active",
            )
        )
    # Story 4: PixelForge downgrade
    for row in rows:
        if row["_id"] == "cust_003":
            row["subscription_tier"] = "pro"
            row["previous_tier"] = "enterprise"
            row["tier_changed_at"] = datetime(2024, 4, 2, 9, 0)
            row["monthly_request_quota"] = 100_000
        if row["_id"] == "cust_007":
            row["subscription_tier"] = "enterprise"
            row["region"] = "us-east-1"
            row["sso_issuer"] = "https://auth-v2.apex.io"
            row["account_manager"] = "Elena Rossi"
        if row["_id"] == "cust_012":
            row["subscription_tier"] = "enterprise"
            row["billing_webhook"] = "https://hooks.northstar.test/billing/v1"
        if row["_id"] == "cust_019":
            row["region"] = "eu-west-1"
            row["previous_region"] = "us-east-1"
        if row["_id"] == "cust_028":
            row["feature_flags"] = {"checkout_v2": False, "new_dashboard": True}
        if row["_id"] == "cust_015":
            row["subscription_tier"] = "enterprise"
    return rows


_STORY_TIERS = {
    "cust_003": "pro",
    "cust_007": "enterprise",
    "cust_012": "enterprise",
    "cust_015": "enterprise",
    "cust_019": "enterprise",
    "cust_022": "enterprise",
    "cust_028": "pro",
    "cust_031": "enterprise",
    "cust_041": "enterprise",
    "cust_044": "pro",
}
_STORY_REGIONS = {
    "cust_007": "us-east-1",
    "cust_019": "eu-west-1",
    "cust_022": "us-west-2",
}
_STORY_FLAGS = {
    "cust_028": {"checkout_v2": False, "new_dashboard": True},
}


def _stories(rng: random.Random) -> tuple[list[Story], dict[str, list[dict[str, Any]]]]:
    tickets: list[dict[str, Any]] = []
    deployments: list[dict[str, Any]] = []
    migrations: list[dict[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    stories: list[Story] = []

    def add_sources(story: Story, *pairs: tuple[str, str]) -> None:
        story.gold_sources.extend(pairs)

    # --- 1. Auth config after SSO migration (Apex Logistics cust_007) ---
    s1 = Story(
        story_id="auth_sso",
        customer_id="cust_007",
        title="Auth failures after SSO issuer migration",
        gold_answer=(
            "Apex Logistics (cust_007) began failing production deployments after migration "
            "mig_auth_sso (2024-05-10) changed the SSO issuer from https://auth-v2.apex.io to "
            "https://auth-v3.apex.io. Deployments dep_apex_fail_1 and dep_apex_fail_2 failed with "
            "AUTH_401. Logs show jwt issuer mismatch: expected auth-v3, got auth-v2. Ticket tkt_1001 "
            "and incident inc_1001 corroborate authentication failures after the migration."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_auth_sso",
                "question": (
                    "Why did customer Apex Logistics (cust_007) begin experiencing deployment "
                    "failures after migration mig_auth_sso, and what evidence supports the most "
                    "likely root cause?"
                ),
            },
            {
                "class": "semantic",
                "id": "sem_auth_incidents",
                "question": "Find incidents involving authentication failures.",
            },
            {
                "class": "simple_lookup",
                "id": "simple_apex_tier",
                "question": "What is customer cust_007's current subscription tier?",
            },
        ],
    )
    mig1 = _base(
        _id="mig_auth_sso",
        migration_id="mig_auth_sso",
        customer_id="cust_007",
        from_version="platform-2.4",
        to_version="platform-3.0",
        started_at=datetime(2024, 5, 10, 8, 0),
        completed_at=datetime(2024, 5, 10, 11, 30),
        status="completed",
        notes=(
            "SSO endpoint changed. Clients MUST update AUTH_ISSUER from "
            "https://auth-v2.apex.io to https://auth-v3.apex.io. Legacy issuer will reject tokens."
        ),
        config_changes={"AUTH_ISSUER": "https://auth-v3.apex.io", "AUTH_AUDIENCE": "apex-api"},
    )
    migrations.append(mig1)
    d1 = _deployment(
        "dep_apex_fail_1",
        "cust_007",
        datetime(2024, 5, 11, 9, 15),
        "failed",
        "AUTH_401",
        "mig_auth_sso",
        "token validation failed: unauthorized issuer",
    )
    d2 = _deployment(
        "dep_apex_fail_2",
        "cust_007",
        datetime(2024, 5, 12, 14, 2),
        "failed",
        "AUTH_401",
        "mig_auth_sso",
        "auth-service returned 401 during rollout",
    )
    deployments.extend([d1, d2])
    t1 = _ticket(
        "tkt_1001",
        "cust_007",
        datetime(2024, 5, 11, 10, 0),
        "Production deploys failing with authentication errors",
        "Since Friday every prod deploy for Apex Logistics fails. Error AUTH_401. Started after the SSO migration.",
        "open",
        "high",
        "authentication",
    )
    tickets.append(t1)
    i1 = _incident(
        "inc_1001",
        "cust_007",
        datetime(2024, 5, 11, 10, 20),
        "Auth failures post SSO migration",
        "Multiple production deployments failing authentication after mig_auth_sso. Suspected stale AUTH_ISSUER on deployer.",
        "sev-1",
        ["tkt_1001"],
        ["dep_apex_fail_1", "dep_apex_fail_2"],
        "stale AUTH_ISSUER still pointing at auth-v2 after SSO issuer cutover",
    )
    incidents.append(i1)
    l1 = _log(
        "log_1001",
        "cust_007",
        datetime(2024, 5, 11, 9, 16),
        "auth-service",
        "ERROR",
        "jwt issuer mismatch: expected https://auth-v3.apex.io, got https://auth-v2.apex.io",
        "dep_apex_fail_1",
        "AUTH_401",
    )
    l2 = _log(
        "log_1002",
        "cust_007",
        datetime(2024, 5, 12, 14, 3),
        "deployer",
        "ERROR",
        "token validation failed for deployer service account against AUTH_ISSUER https://auth-v2.apex.io",
        "dep_apex_fail_2",
        "AUTH_401",
    )
    logs.extend([l1, l2])
    add_sources(
        s1,
        ("migrations", "mig_auth_sso"),
        ("deployments", "dep_apex_fail_1"),
        ("deployments", "dep_apex_fail_2"),
        ("tickets", "tkt_1001"),
        ("incidents", "inc_1001"),
        ("logs", "log_1001"),
        ("logs", "log_1002"),
        ("customers", "cust_007"),
    )
    stories.append(s1)

    # --- Apex auth precursors (March timeout, April token TTL) for variable-K ---
    tickets.append(
        _ticket(
            "tkt_apex_mar",
            "cust_007",
            datetime(2024, 3, 8, 15, 40),
            "Users dropped from dashboard after sitting idle",
            "Apex operators say the console logs them out if they step away for lunch. "
            "They have to sign in again. Started this week on prod.",
            "resolved",
            "medium",
            "authentication",
        )
    )
    incidents.append(
        _incident(
            "inc_apex_mar",
            "cust_007",
            datetime(2024, 3, 8, 16, 10),
            "Idle sessions ending early",
            "Prod sessions for Apex end after a short idle period. Operators report sudden logouts, "
            "not password failures.",
            "sev-3",
            ["tkt_apex_mar"],
            ["dep_apex_mar"],
            "session idle-timeout was shortened on the dashboard cookie",
        )
    )
    deployments.append(
        _deployment(
            "dep_apex_mar",
            "cust_007",
            datetime(2024, 3, 7, 11, 0),
            "success",
            None,
            None,
            "dashboard cookie max-age reduced; SESSION_IDLE_TIMEOUT_SEC set to 900",
        )
    )
    logs.extend(
        [
            _log(
                "log_apex_mar_1",
                "cust_007",
                datetime(2024, 3, 8, 13, 5),
                "auth-service",
                "WARN",
                "session cookie expired after idle period; SESSION_IDLE_TIMEOUT_SEC=900",
                "dep_apex_mar",
                "SESSION_EXPIRED",
            ),
            _log(
                "log_apex_mar_2",
                "cust_007",
                datetime(2024, 3, 8, 14, 22),
                "api-gateway",
                "INFO",
                "rejected request: dashboard session cookie expired for operator workspace",
                "dep_apex_mar",
                "SESSION_EXPIRED",
            ),
        ]
    )
    tickets.append(
        _ticket(
            "tkt_apex_apr",
            "cust_007",
            datetime(2024, 4, 16, 9, 30),
            "Integrations keep prompting for sign-in during the workday",
            "Apex batch jobs that used to run for hours now stop and ask for a new sign-in "
            "every so often. Worse than last month's idle-logout reports.",
            "open",
            "high",
            "authentication",
        )
    )
    incidents.append(
        _incident(
            "inc_apex_apr",
            "cust_007",
            datetime(2024, 4, 16, 10, 5),
            "Short-lived access tokens interrupting jobs",
            "Apex worker jobs fail mid-run and require a fresh sign-in. Pattern matches a shorter "
            "access-token lifetime, not an idle cookie.",
            "sev-2",
            ["tkt_apex_apr"],
            ["dep_apex_apr"],
            "ACCESS_TOKEN_TTL_SEC reduced; jobs outlive the token",
        )
    )
    deployments.append(
        _deployment(
            "dep_apex_apr",
            "cust_007",
            datetime(2024, 4, 15, 18, 20),
            "success",
            None,
            None,
            "auth-service ACCESS_TOKEN_TTL_SEC changed from 14400 to 1800",
        )
    )
    logs.extend(
        [
            _log(
                "log_apex_apr_1",
                "cust_007",
                datetime(2024, 4, 16, 8, 40),
                "auth-service",
                "WARN",
                "access token expired before job completed; ACCESS_TOKEN_TTL_SEC=1800",
                "dep_apex_apr",
                "TOKEN_TTL",
            ),
            _log(
                "log_apex_apr_2",
                "cust_007",
                datetime(2024, 4, 16, 9, 12),
                "billing-worker",
                "ERROR",
                "re-authentication required: access token TTL elapsed during invoice export",
                "dep_apex_apr",
                "TOKEN_TTL",
            ),
            _log(
                "log_apex_apr_3",
                "cust_007",
                datetime(2024, 4, 16, 11, 3),
                "scheduler",
                "ERROR",
                "job aborted: token lifetime shorter than scheduled window",
                "dep_apex_apr",
                "TOKEN_TTL",
            ),
        ]
    )

    # --- 2. Billing webhook (Northstar Payments cust_012) ---
    s2 = Story(
        story_id="billing_webhook",
        customer_id="cust_012",
        title="Invoice pipeline broken after webhook URL change",
        gold_answer=(
            "Northstar Payments (cust_012) invoice failures started after migration mig_bill_wh "
            "changed the billing webhook from /billing/v1 to /billing/v2. Logs show HTTP 404 to the "
            "old URL. Ticket tkt_2001 and incident inc_2001 describe missing invoices."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_billing",
                "question": (
                    "Why did Northstar Payments (cust_012) start missing invoices after "
                    "migration mig_bill_wh, and which records prove the root cause?"
                ),
            },
            {
                "class": "semantic",
                "id": "sem_billing",
                "question": "Find tickets about invoice or billing webhook problems.",
            },
            {
                "class": "simple_lookup",
                "id": "simple_northstar_region",
                "question": "What region is customer cust_012 in?",
            },
        ],
    )
    migrations.append(
        _base(
            _id="mig_bill_wh",
            migration_id="mig_bill_wh",
            customer_id="cust_012",
            from_version="billing-3.1",
            to_version="billing-4.0",
            started_at=datetime(2024, 3, 18, 7, 0),
            completed_at=datetime(2024, 3, 18, 9, 0),
            status="completed",
            notes="Webhook path moved to https://hooks.northstar.test/billing/v2. v1 returns 404 after 2024-03-18.",
            config_changes={"BILLING_WEBHOOK_URL": "https://hooks.northstar.test/billing/v2"},
        )
    )
    deployments.append(
        _deployment(
            "dep_ns_bill_1",
            "cust_012",
            datetime(2024, 3, 19, 8, 0),
            "success",
            None,
            "mig_bill_wh",
            "billing-worker rolled out; still posting to v1 URL in config map",
        )
    )
    tickets.append(
        _ticket(
            "tkt_2001",
            "cust_012",
            datetime(2024, 3, 19, 11, 0),
            "Invoices not arriving after billing upgrade",
            "Finance has not received invoices since March 18. Webhook dashboard shows failures.",
            "open",
            "high",
            "billing",
        )
    )
    incidents.append(
        _incident(
            "inc_2001",
            "cust_012",
            datetime(2024, 3, 19, 12, 0),
            "Billing pipeline down",
            "Invoice webhooks returning 404 after billing-4.0 migration.",
            "sev-2",
            ["tkt_2001"],
            ["dep_ns_bill_1"],
            "billing-worker still calling retired /billing/v1 webhook",
        )
    )
    logs.append(
        _log(
            "log_2001",
            "cust_012",
            datetime(2024, 3, 19, 8, 5),
            "billing-worker",
            "ERROR",
            "POST https://hooks.northstar.test/billing/v1 -> HTTP 404 webhook_not_found",
            "dep_ns_bill_1",
            "WH_404",
        )
    )
    add_sources(
        s2,
        ("migrations", "mig_bill_wh"),
        ("deployments", "dep_ns_bill_1"),
        ("tickets", "tkt_2001"),
        ("incidents", "inc_2001"),
        ("logs", "log_2001"),
        ("customers", "cust_012"),
    )
    stories.append(s2)

    # --- Northstar identity cutover: distributed evidence (no single record has the cause) ---
    tickets.append(
        _ticket(
            "tkt_ns_login",
            "cust_012",
            datetime(2024, 6, 4, 10, 15),
            "Intermittent login failures after recent platform changes",
            "Northstar staff report they sometimes cannot sign in to production after last week's "
            "platform work. Failures come and go. No invoice or billing symptoms.",
            "open",
            "high",
            "authentication",
        )
    )
    migrations.append(
        _base(
            _id="mig_ns_identity",
            migration_id="mig_ns_identity",
            customer_id="cust_012",
            from_version="identity-2.1",
            to_version="identity-3.0",
            started_at=datetime(2024, 6, 3, 7, 0),
            completed_at=datetime(2024, 6, 3, 9, 30),
            status="completed",
            notes=(
                "Identity platform cutover. OIDC issuer URL is now "
                "https://id.northstar.test/realms/prod. Update relying parties before the next release."
            ),
            config_changes={"OIDC_ISSUER": "https://id.northstar.test/realms/prod"},
        )
    )
    deployments.append(
        _deployment(
            "dep_ns_stale",
            "cust_012",
            datetime(2024, 6, 4, 8, 10),
            "success",
            None,
            None,
            "auth-service rollout kept the previous authentication configuration in the runtime map",
        )
    )
    logs.append(
        _log(
            "log_ns_jwt",
            "cust_012",
            datetime(2024, 6, 4, 8, 18),
            "auth-service",
            "ERROR",
            "token validation rejected because issuer did not match expected value",
            "dep_ns_stale",
            None,
        )
    )

    # --- 3. TLS after region move (Harbor Health cust_019) ---
    s3 = Story(
        story_id="tls_region",
        customer_id="cust_019",
        title="TLS handshake failures after region migration",
        gold_answer=(
            "Harbor Health (cust_019) moved from us-east-1 to eu-west-1 via mig_region_eu. "
            "The eu-west-1 load balancer certificate expired. Deployments fail with "
            "TLS_HANDSHAKE_ERROR and logs show certificate verify failed: certificate has expired."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_tls",
                "question": (
                    "Why did Harbor Health (cust_019) deployments fail after the region migration "
                    "to eu-west-1, and what evidence supports the root cause?"
                ),
            }
        ],
    )
    migrations.append(
        _base(
            _id="mig_region_eu",
            migration_id="mig_region_eu",
            customer_id="cust_019",
            from_version="region-us-east-1",
            to_version="region-eu-west-1",
            started_at=datetime(2024, 6, 1, 6, 0),
            completed_at=datetime(2024, 6, 2, 18, 0),
            status="completed",
            notes="Workloads moved to eu-west-1. TLS cert for lb-eu.harbor-health.test expires 2024-06-03 unless rotated.",
            config_changes={"REGION": "eu-west-1", "LB_HOST": "lb-eu.harbor-health.test"},
        )
    )
    deployments.append(
        _deployment(
            "dep_hh_tls_1",
            "cust_019",
            datetime(2024, 6, 4, 9, 0),
            "failed",
            "TLS_HANDSHAKE_ERROR",
            "mig_region_eu",
            "handshake failed talking to lb-eu.harbor-health.test",
        )
    )
    tickets.append(
        _ticket(
            "tkt_3001",
            "cust_019",
            datetime(2024, 6, 4, 9, 30),
            "Cannot deploy after EU migration",
            "All prod deploys fail TLS handshake since the region move.",
            "open",
            "critical",
            "networking",
        )
    )
    incidents.append(
        _incident(
            "inc_3001",
            "cust_019",
            datetime(2024, 6, 4, 10, 0),
            "Expired TLS cert on EU load balancer",
            "Certificate for lb-eu.harbor-health.test expired after region migration.",
            "sev-1",
            ["tkt_3001"],
            ["dep_hh_tls_1"],
            "expired TLS certificate on eu-west-1 load balancer",
        )
    )
    logs.append(
        _log(
            "log_3001",
            "cust_019",
            datetime(2024, 6, 4, 9, 1),
            "api-gateway",
            "ERROR",
            "certificate verify failed: certificate has expired (lb-eu.harbor-health.test)",
            "dep_hh_tls_1",
            "TLS_HANDSHAKE_ERROR",
        )
    )
    add_sources(
        s3,
        ("migrations", "mig_region_eu"),
        ("deployments", "dep_hh_tls_1"),
        ("tickets", "tkt_3001"),
        ("incidents", "inc_3001"),
        ("logs", "log_3001"),
        ("customers", "cust_019"),
    )
    stories.append(s3)

    # --- 4. Rate limit after downgrade (PixelForge cust_003) ---
    s4 = Story(
        story_id="rate_limit",
        customer_id="cust_003",
        title="API 429s after enterprise to pro downgrade",
        gold_answer=(
            "PixelForge (cust_003) was downgraded from enterprise to pro on 2024-04-02 with a "
            "monthly_request_quota of 100000. Logs show 429 Too Many Requests from api-gateway. "
            "Tickets report API timeouts; there is no migration — the cause is the plan change."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_ratelimit",
                "question": (
                    "Why did PixelForge (cust_003) start seeing API timeouts and 429 errors in April, "
                    "and what customer-record change explains it?"
                ),
            },
            {
                "class": "simple_lookup",
                "id": "simple_pixelforge_tier",
                "question": "What is customer cust_003's current subscription tier?",
            },
        ],
    )
    tickets.append(
        _ticket(
            "tkt_4001",
            "cust_003",
            datetime(2024, 4, 5, 13, 0),
            "API timeouts and 429s after plan change",
            "Our integration started failing with HTTP 429 shortly after the billing plan was changed.",
            "open",
            "high",
            "api",
        )
    )
    incidents.append(
        _incident(
            "inc_4001",
            "cust_003",
            datetime(2024, 4, 5, 14, 0),
            "Rate limiting after downgrade",
            "Customer hit pro-tier quota after leaving enterprise.",
            "sev-3",
            ["tkt_4001"],
            [],
            "subscription downgrade reduced monthly_request_quota to 100000",
        )
    )
    logs.append(
        _log(
            "log_4001",
            "cust_003",
            datetime(2024, 4, 5, 12, 44),
            "api-gateway",
            "WARN",
            "429 Too Many Requests quota=100000 plan=pro customer=cust_003",
            None,
            "HTTP_429",
        )
    )
    add_sources(
        s4,
        ("customers", "cust_003"),
        ("tickets", "tkt_4001"),
        ("incidents", "inc_4001"),
        ("logs", "log_4001"),
    )
    stories.append(s4)

    # --- 5. IAM after cloud migration (Redwood Analytics cust_022) ---
    s5 = Story(
        story_id="iam_gcp",
        customer_id="cust_022",
        title="GCS AccessDenied after AWS to GCP migration",
        gold_answer=(
            "Redwood Analytics (cust_022) migrated from AWS to GCP (mig_aws_gcp). Deployments fail "
            "with AccessDenied because service account mare-runtime@redwood.iam.gserviceaccount.com "
            "is missing roles/storage.objectAdmin on the artifacts bucket."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_iam",
                "question": (
                    "Why did Redwood Analytics (cust_022) deployments fail after the AWS to GCP "
                    "migration, and what permission is missing?"
                ),
            }
        ],
    )
    migrations.append(
        _base(
            _id="mig_aws_gcp",
            migration_id="mig_aws_gcp",
            customer_id="cust_022",
            from_version="aws-eks-1.2",
            to_version="gcp-gke-1.0",
            started_at=datetime(2024, 2, 12, 10, 0),
            completed_at=datetime(2024, 2, 14, 16, 0),
            status="completed",
            notes=(
                "Cut over artifact storage to gs://redwood-artifacts. Grant "
                "mare-runtime@redwood.iam.gserviceaccount.com roles/storage.objectAdmin."
            ),
            config_changes={"CLOUD": "gcp", "ARTIFACT_BUCKET": "gs://redwood-artifacts"},
        )
    )
    deployments.append(
        _deployment(
            "dep_rw_1",
            "cust_022",
            datetime(2024, 2, 15, 9, 0),
            "failed",
            "AccessDenied",
            "mig_aws_gcp",
            "cannot upload image to gs://redwood-artifacts",
        )
    )
    tickets.append(
        _ticket(
            "tkt_5001",
            "cust_022",
            datetime(2024, 2, 15, 9, 40),
            "Deploys fail writing to GCS",
            "Since the GCP migration, deployer cannot push artifacts. AccessDenied.",
            "open",
            "high",
            "platform",
        )
    )
    incidents.append(
        _incident(
            "inc_5001",
            "cust_022",
            datetime(2024, 2, 15, 10, 0),
            "Missing GCS IAM role after cloud migration",
            "Runtime SA missing objectAdmin on artifacts bucket.",
            "sev-2",
            ["tkt_5001"],
            ["dep_rw_1"],
            "missing roles/storage.objectAdmin on mare-runtime service account",
        )
    )
    logs.append(
        _log(
            "log_5001",
            "cust_022",
            datetime(2024, 2, 15, 9, 1),
            "deployer",
            "ERROR",
            "AccessDenied: service account mare-runtime@redwood.iam.gserviceaccount.com missing roles/storage.objectAdmin on gs://redwood-artifacts",
            "dep_rw_1",
            "AccessDenied",
        )
    )
    add_sources(
        s5,
        ("migrations", "mig_aws_gcp"),
        ("deployments", "dep_rw_1"),
        ("tickets", "tkt_5001"),
        ("incidents", "inc_5001"),
        ("logs", "log_5001"),
        ("customers", "cust_022"),
    )
    stories.append(s5)

    # --- 6. Cache invalidation (Quilt Retail cust_031) ---
    s6 = Story(
        story_id="cache_schema",
        customer_id="cust_031",
        title="Stale catalog cache after schema v4",
        gold_answer=(
            "Quilt Retail (cust_031) migrated catalog schema to v4 (mig_catalog_v4) but the "
            "storefront cache still served schema version 3, producing wrong prices. Logs show "
            "stale product schema version 3."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_cache",
                "question": (
                    "Why did Quilt Retail (cust_031) show wrong storefront prices after the catalog "
                    "schema migration, and what evidence supports cache invalidation as the cause?"
                ),
            }
        ],
    )
    migrations.append(
        _base(
            _id="mig_catalog_v4",
            migration_id="mig_catalog_v4",
            customer_id="cust_031",
            from_version="catalog-schema-3",
            to_version="catalog-schema-4",
            started_at=datetime(2024, 7, 8, 4, 0),
            completed_at=datetime(2024, 7, 8, 6, 0),
            status="completed",
            notes="Price fields moved under pricing.amount. Flush storefront cache keys catalog:v3:* after cutover.",
            config_changes={"CATALOG_SCHEMA": "4"},
        )
    )
    deployments.append(
        _deployment(
            "dep_quilt_1",
            "cust_031",
            datetime(2024, 7, 8, 7, 0),
            "success",
            None,
            "mig_catalog_v4",
            "storefront rolled; cache TTL left at 24h",
        )
    )
    tickets.append(
        _ticket(
            "tkt_6001",
            "cust_031",
            datetime(2024, 7, 8, 12, 0),
            "Wrong prices on storefront after catalog upgrade",
            "Customers seeing yesterday's prices. Started right after catalog v4.",
            "open",
            "high",
            "storefront",
        )
    )
    incidents.append(
        _incident(
            "inc_6001",
            "cust_031",
            datetime(2024, 7, 8, 12, 30),
            "Stale catalog cache after schema v4",
            "storefront cache keys catalog:v3 still hot.",
            "sev-2",
            ["tkt_6001"],
            ["dep_quilt_1"],
            "missing cache invalidation for catalog:v3 keys after schema v4",
        )
    )
    logs.append(
        _log(
            "log_6001",
            "cust_031",
            datetime(2024, 7, 8, 11, 55),
            "storefront",
            "WARN",
            "cache key miss / stale product schema version 3 for sku=QR-1092; expected schema 4",
            "dep_quilt_1",
            "CACHE_STALE",
        )
    )
    add_sources(
        s6,
        ("migrations", "mig_catalog_v4"),
        ("deployments", "dep_quilt_1"),
        ("tickets", "tkt_6001"),
        ("incidents", "inc_6001"),
        ("logs", "log_6001"),
        ("customers", "cust_031"),
    )
    stories.append(s6)

    # --- 7. API key rotation (Orbit Media cust_041) ---
    s7 = Story(
        story_id="api_key",
        customer_id="cust_041",
        title="Incomplete API key rotation",
        gold_answer=(
            "Orbit Media (cust_041) rotated API keys in mig_key_rot. billing-worker deployments "
            "still use the old key and logs show invalid_api_key."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_apikey",
                "question": (
                    "Why is Orbit Media (cust_041) billing-worker failing after the API key "
                    "rotation, and which service still uses the old key?"
                ),
            }
        ],
    )
    migrations.append(
        _base(
            _id="mig_key_rot",
            migration_id="mig_key_rot",
            customer_id="cust_041",
            from_version="keys-2023",
            to_version="keys-2024-07",
            started_at=datetime(2024, 7, 20, 9, 0),
            completed_at=datetime(2024, 7, 20, 10, 0),
            status="completed",
            notes="Old live key om_live_old_8f2 revoked at 10:00 UTC. All workers must load om_live_new_91c.",
            config_changes={"API_KEY": "om_live_new_91c"},
        )
    )
    deployments.append(
        _deployment(
            "dep_orbit_bill",
            "cust_041",
            datetime(2024, 7, 20, 11, 0),
            "failed",
            "invalid_api_key",
            "mig_key_rot",
            "billing-worker secret not refreshed",
        )
    )
    tickets.append(
        _ticket(
            "tkt_7001",
            "cust_041",
            datetime(2024, 7, 20, 11, 20),
            "Billing worker auth failing after key rotation",
            "Only billing-worker is down. Other services fine after key rotation.",
            "open",
            "high",
            "billing",
        )
    )
    incidents.append(
        _incident(
            "inc_7001",
            "cust_041",
            datetime(2024, 7, 20, 11, 30),
            "Incomplete API key rotation",
            "billing-worker still presenting revoked om_live_old_8f2.",
            "sev-2",
            ["tkt_7001"],
            ["dep_orbit_bill"],
            "billing-worker secret not updated to om_live_new_91c",
        )
    )
    logs.append(
        _log(
            "log_7001",
            "cust_041",
            datetime(2024, 7, 20, 11, 1),
            "billing-worker",
            "ERROR",
            "invalid_api_key: key om_live_old_8f2 revoked during mig_key_rot",
            "dep_orbit_bill",
            "invalid_api_key",
        )
    )
    add_sources(
        s7,
        ("migrations", "mig_key_rot"),
        ("deployments", "dep_orbit_bill"),
        ("tickets", "tkt_7001"),
        ("incidents", "inc_7001"),
        ("logs", "log_7001"),
        ("customers", "cust_041"),
    )
    stories.append(s7)

    # --- 8. Connection pool (Cascade Bank cust_015) ---
    s8 = Story(
        story_id="pool_exhaust",
        customer_id="cust_015",
        title="Connection pool exhausted after misconfigured deploy",
        gold_answer=(
            "Cascade Bank (cust_015) deployment dep_cascade_pool reduced mongo pool size to 5. "
            "During a traffic spike, logs show MongoServerError: connection pool exhausted and "
            "tickets report intermittent 500s."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_pool",
                "question": (
                    "Why did Cascade Bank (cust_015) see intermittent 500s and connection pool "
                    "errors after deployment dep_cascade_pool?"
                ),
            }
        ],
    )
    deployments.append(
        _deployment(
            "dep_cascade_pool",
            "cust_015",
            datetime(2024, 5, 22, 3, 0),
            "success",
            None,
            None,
            "MONGO_MAX_POOL_SIZE set to 5 (was 100) due to copied dev manifest",
        )
    )
    tickets.append(
        _ticket(
            "tkt_8001",
            "cust_015",
            datetime(2024, 5, 22, 16, 0),
            "Intermittent 500s during peak",
            "Online banking 500s around 9am and 5pm. Started after last night's deploy.",
            "open",
            "critical",
            "reliability",
        )
    )
    incidents.append(
        _incident(
            "inc_8001",
            "cust_015",
            datetime(2024, 5, 22, 16, 20),
            "Mongo connection pool exhausted",
            "Pool size 5 cannot serve peak traffic.",
            "sev-1",
            ["tkt_8001"],
            ["dep_cascade_pool"],
            "MONGO_MAX_POOL_SIZE=5 shipped in prod deploy",
        )
    )
    logs.append(
        _log(
            "log_8001",
            "cust_015",
            datetime(2024, 5, 22, 15, 55),
            "api-gateway",
            "ERROR",
            "MongoServerError: connection pool exhausted maxPoolSize=5",
            "dep_cascade_pool",
            "POOL_EXHAUSTED",
        )
    )
    add_sources(
        s8,
        ("deployments", "dep_cascade_pool"),
        ("tickets", "tkt_8001"),
        ("incidents", "inc_8001"),
        ("logs", "log_8001"),
        ("customers", "cust_015"),
    )
    stories.append(s8)

    # --- 9. Feature flag (Lumen Education cust_028) ---
    s9 = Story(
        story_id="feature_flag",
        customer_id="cust_028",
        title="Blank dashboard because checkout_v2 flag off",
        gold_answer=(
            "Lumen Education (cust_028) deployed the new dashboard (dep_lumen_ui) which depends on "
            "feature flag checkout_v2. The customer record has checkout_v2=false, and logs say "
            "feature checkout_v2 disabled for tenant, causing a blank dashboard."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_flag",
                "question": (
                    "Why did Lumen Education (cust_028) users see a blank dashboard after the new "
                    "UI deployment, and which feature flag is involved?"
                ),
            }
        ],
    )
    deployments.append(
        _deployment(
            "dep_lumen_ui",
            "cust_028",
            datetime(2024, 4, 18, 12, 0),
            "success",
            None,
            None,
            "new dashboard requires checkout_v2 flag",
        )
    )
    tickets.append(
        _ticket(
            "tkt_9001",
            "cust_028",
            datetime(2024, 4, 18, 13, 0),
            "Blank dashboard after UI release",
            "Students see an empty home page after this morning's UI deploy.",
            "open",
            "high",
            "frontend",
        )
    )
    incidents.append(
        _incident(
            "inc_9001",
            "cust_028",
            datetime(2024, 4, 18, 13, 15),
            "Dashboard blank — feature flag off",
            "checkout_v2 disabled for tenant.",
            "sev-2",
            ["tkt_9001"],
            ["dep_lumen_ui"],
            "checkout_v2 feature flag false on customer record",
        )
    )
    logs.append(
        _log(
            "log_9001",
            "cust_028",
            datetime(2024, 4, 18, 12, 5),
            "storefront",
            "INFO",
            "feature checkout_v2 disabled for tenant cust_028; dashboard module skipped",
            "dep_lumen_ui",
            "FLAG_OFF",
        )
    )
    add_sources(
        s9,
        ("customers", "cust_028"),
        ("deployments", "dep_lumen_ui"),
        ("tickets", "tkt_9001"),
        ("incidents", "inc_9001"),
        ("logs", "log_9001"),
    )
    stories.append(s9)

    # --- 10. Timezone/DST (Solstice Travel cust_044) ---
    s10 = Story(
        story_id="dst_tz",
        customer_id="cust_044",
        title="Scheduler 1h late after DST plus 2.8.1 release",
        gold_answer=(
            "Solstice Travel (cust_044) deployed scheduler 2.8.1 (dep_solstice_sched) which uses "
            "fixed UTC+0 offsets. After the March DST change, jobs fired 1 hour late. Tickets "
            "report missed booking confirmations."
        ),
        questions=[
            {
                "class": "complex_multihop",
                "id": "mh_dst",
                "question": (
                    "Why did Solstice Travel (cust_044) miss booking confirmations after the "
                    "scheduler 2.8.1 deployment around the DST change?"
                ),
            }
        ],
    )
    deployments.append(
        _deployment(
            "dep_solstice_sched",
            "cust_044",
            datetime(2024, 3, 9, 2, 0),
            "success",
            None,
            None,
            "scheduler 2.8.1 uses fixed offset, not timezone-aware Europe/London",
        )
    )
    tickets.append(
        _ticket(
            "tkt_1101",
            "cust_044",
            datetime(2024, 3, 11, 9, 0),
            "Missed booking confirmations after clocks changed",
            "Confirmation emails going out an hour late since the weekend.",
            "open",
            "high",
            "scheduler",
        )
    )
    incidents.append(
        _incident(
            "inc_1101",
            "cust_044",
            datetime(2024, 3, 11, 9, 30),
            "Scheduler DST bug",
            "Jobs 1h late after DST; scheduler 2.8.1 not timezone aware.",
            "sev-2",
            ["tkt_1101"],
            ["dep_solstice_sched"],
            "scheduler 2.8.1 fixed UTC offset vs Europe/London DST",
        )
    )
    logs.append(
        _log(
            "log_1101",
            "cust_044",
            datetime(2024, 3, 11, 8, 0),
            "scheduler",
            "WARN",
            "job booking-confirm fired at 08:00 UTC expected 07:00 UTC (DST gap) version=2.8.1",
            "dep_solstice_sched",
            "TZ_DRIFT",
        )
    )
    add_sources(
        s10,
        ("deployments", "dep_solstice_sched"),
        ("tickets", "tkt_1101"),
        ("incidents", "inc_1101"),
        ("logs", "log_1101"),
        ("customers", "cust_044"),
    )
    stories.append(s10)

    return stories, {
        "tickets": tickets,
        "deployments": deployments,
        "migrations": migrations,
        "incidents": incidents,
        "logs": logs,
    }


def _deployment(
    _id: str,
    customer_id: str,
    started: datetime,
    status: str,
    error_code: str | None,
    migration_id: str | None,
    excerpt: str,
) -> dict[str, Any]:
    return _base(
        _id=_id,
        deployment_id=_id,
        customer_id=customer_id,
        environment="prod",
        status=status,
        started_at=started,
        finished_at=started + timedelta(minutes=12),
        version="rel-" + started.strftime("%Y%m%d"),
        migration_id=migration_id,
        error_code=error_code,
        logs_excerpt=excerpt,
        service=rng_pick_service(_id),
    )


def rng_pick_service(_id: str) -> str:
    return SERVICES[sum(ord(c) for c in _id) % len(SERVICES)]


def _ticket(
    _id: str,
    customer_id: str,
    created: datetime,
    subject: str,
    body: str,
    status: str,
    severity: str,
    category: str,
) -> dict[str, Any]:
    return _base(
        _id=_id,
        ticket_id=_id,
        customer_id=customer_id,
        subject=subject,
        body=body,
        status=status,
        severity=severity,
        created_at=created,
        resolved_at=None,
        category=category,
    )


def _incident(
    _id: str,
    customer_id: str,
    opened: datetime,
    title: str,
    description: str,
    severity: str,
    tickets: list[str],
    deployments: list[str],
    root_cause: str,
) -> dict[str, Any]:
    return _base(
        _id=_id,
        incident_id=_id,
        customer_id=customer_id,
        title=title,
        description=description,
        severity=severity,
        opened_at=opened,
        closed_at=None,
        related_ticket_ids=tickets,
        related_deployment_ids=deployments,
        root_cause=root_cause,
        status="open",
    )


def _log(
    _id: str,
    customer_id: str,
    ts: datetime,
    service: str,
    level: str,
    message: str,
    deployment_id: str | None,
    error_code: str | None,
) -> dict[str, Any]:
    return _base(
        _id=_id,
        log_id=_id,
        customer_id=customer_id,
        timestamp=ts,
        service=service,
        level=level,
        message=message,
        deployment_id=deployment_id,
        error_code=error_code,
        trace_id=f"tr-{_id}",
    )


def _noise_tickets(rng: random.Random, n: int) -> list[dict[str, Any]]:
    subjects = [
        "Cannot reset password",
        "Slow dashboard load",
        "Export CSV truncated",
        "SSO login loop",
        "Invoice PDF missing logo",
        "Webhook retry storm",
        "Mobile app crash on iOS 17",
        "Permission denied on report",
    ]
    cats = ["account", "performance", "billing", "frontend", "api"]
    out = []
    for i in range(n):
        cid = f"cust_{rng.randint(1, 50):03d}"
        created = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 220), hours=rng.randint(0, 23))
        out.append(
            _ticket(
                f"tkt_{20000+i}",
                cid,
                created,
                rng.choice(subjects),
                "Customer reports an issue. No relation to the gold multi-hop stories.",
                rng.choice(["open", "pending", "resolved"]),
                rng.choice(["low", "medium", "high"]),
                rng.choice(cats),
            )
        )
    return out


def _noise_deployments(rng: random.Random, n: int) -> list[dict[str, Any]]:
    out = []
    for i in range(n):
        cid = f"cust_{rng.randint(1, 50):03d}"
        started = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 220), hours=rng.randint(0, 23))
        status = "success" if rng.random() > 0.12 else "failed"
        err = None if status == "success" else rng.choice(["TIMEOUT", "IMAGE_PULL", "HEALTHCHECK"])
        out.append(
            _deployment(
                f"dep_n_{i:04d}",
                cid,
                started,
                status,
                err,
                None,
                "routine rollout" if status == "success" else "non-story failure",
            )
        )
        out[-1]["environment"] = rng.choice(ENVIRONMENTS)
    return out


def _noise_migrations(rng: random.Random, n: int) -> list[dict[str, Any]]:
    out = []
    for i in range(max(0, n)):
        cid = f"cust_{rng.randint(1, 50):03d}"
        started = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 200))
        out.append(
            _base(
                _id=f"mig_n_{i:03d}",
                migration_id=f"mig_n_{i:03d}",
                customer_id=cid,
                from_version=f"app-1.{rng.randint(0, 5)}",
                to_version=f"app-1.{rng.randint(6, 9)}",
                started_at=started,
                completed_at=started + timedelta(hours=3),
                status="completed",
                notes="Routine version bump. No known incident linkage.",
                config_changes={"APP_VERSION": f"1.{rng.randint(6, 9)}"},
            )
        )
    return out


def _noise_incidents(rng: random.Random, n: int) -> list[dict[str, Any]]:
    titles = [
        "Elevated latency in us-west-2",
        "Disk pressure on scheduler",
        "CDN cache miss spike",
        "Email provider bounce rate",
        "Canary mismatch on staging",
    ]
    out = []
    for i in range(n):
        cid = f"cust_{rng.randint(1, 50):03d}"
        opened = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 220))
        out.append(
            _incident(
                f"inc_{20000+i}",
                cid,
                opened,
                rng.choice(titles),
                "Background incident unrelated to gold causal stories.",
                rng.choice(["sev-3", "sev-4"]),
                [],
                [],
                "unrelated operational noise",
            )
        )
    return out


def _noise_logs(rng: random.Random, n: int) -> list[dict[str, Any]]:
    msgs = [
        "request completed status=200 latency_ms=42",
        "cache hit key=session:{id}",
        "scheduled job ok",
        "healthcheck passed",
        "retrying downstream call attempt=1",
        "user login success",
        "exported report rows=120",
    ]
    out = []
    for i in range(n):
        cid = f"cust_{rng.randint(1, 50):03d}"
        ts = datetime(2024, 1, 1) + timedelta(
            days=rng.randint(0, 220), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        out.append(
            _log(
                f"log_n_{i:05d}",
                cid,
                ts,
                rng.choice(SERVICES),
                rng.choice(["INFO", "INFO", "INFO", "WARN", "DEBUG"]),
                rng.choice(msgs),
                None,
                None,
            )
        )
    return out


def _gold(stories: list[Story]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for story in stories:
        sources = [
            {"database": RAW_DB, "collection": coll, "document_id": did}
            for coll, did in story.gold_sources
        ]
        for q in story.questions:
            # Simple lookups only need the customer record.
            gold_sources = sources
            gold_answer = story.gold_answer
            if q["class"] == "simple_lookup":
                gold_sources = [
                    {"database": RAW_DB, "collection": "customers", "document_id": story.customer_id}
                ]
                if "subscription" in q["question"]:
                    # filled later conceptually; keep story-level answer too
                    gold_answer = story.gold_answer.split(".")[0] + " (see customer record for tier)."
            if q["class"] == "semantic":
                gold_sources = [s for s in sources if s["collection"] in {"incidents", "tickets"}]
            queries.append(
                {
                    "id": q["id"],
                    "class": q["class"],
                    "question": q["question"],
                    "gold_answer": gold_answer,
                    "gold_sources": gold_sources,
                    "story_id": story.story_id,
                }
            )
    return queries


def _capability_queries(
    customers: list[dict[str, Any]], incidents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Queries where chunk-everything Top-K RAG is structurally weak.

    These do not name the downstream entity IDs (bridge), require a full-collection
    count (aggregation), require proving absence (negative), split the cause across
    records (distributed), or need a gold set whose size is not known in advance
    (variable_k).
    """
    enterprise = [c for c in customers if c.get("subscription_tier") == "enterprise"]
    cedar_incidents = [inc for inc in incidents if inc.get("customer_id") == "cust_004"]
    cedar_april = [
        inc
        for inc in cedar_incidents
        if isinstance(inc.get("opened_at"), datetime)
        and inc["opened_at"].year == 2024
        and inc["opened_at"].month == 4
    ]
    if cedar_april:
        raise RuntimeError("capability query assumes Cedar Systems has no April 2024 incidents")

    sso_sources = [
        {"database": RAW_DB, "collection": "migrations", "document_id": "mig_auth_sso"},
        {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_fail_1"},
        {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_fail_2"},
        {"database": RAW_DB, "collection": "tickets", "document_id": "tkt_1001"},
        {"database": RAW_DB, "collection": "incidents", "document_id": "inc_1001"},
        {"database": RAW_DB, "collection": "logs", "document_id": "log_1001"},
        {"database": RAW_DB, "collection": "logs", "document_id": "log_1002"},
        {"database": RAW_DB, "collection": "customers", "document_id": "cust_007"},
    ]
    return [
        {
            "id": "bridge_elena_may_deploys",
            "class": "bridge",
            "question": (
                "An enterprise customer in us-east-1 whose account manager is Elena Rossi "
                "started failing production deployments in May 2024. What is the most "
                "likely root cause?"
            ),
            "gold_answer": (
                "The customer is Apex Logistics (cust_007). After migration mig_auth_sso "
                "(2024-05-10) changed AUTH_ISSUER from https://auth-v2.apex.io to "
                "https://auth-v3.apex.io, production deployments dep_apex_fail_1 and "
                "dep_apex_fail_2 failed with AUTH_401 (unauthorized / jwt issuer mismatch)."
            ),
            "gold_sources": sso_sources,
            "story_id": "auth_sso",
            "must_contain_groups": [
                ["cust_007", "apex"],
                ["auth_401", "issuer", "mig_auth_sso", "sso"],
            ],
        },
        {
            "id": "agg_enterprise_count",
            "class": "aggregation",
            "question": (
                "How many customers in mare_demo are currently on the enterprise "
                "subscription tier?"
            ),
            "gold_answer": f"{len(enterprise)} customers are on the enterprise subscription tier.",
            "gold_sources": [
                {"database": RAW_DB, "collection": "customers", "document_id": c["_id"]}
                for c in enterprise
            ],
            "story_id": None,
            "must_contain_all": [str(len(enterprise))],
        },
        {
            "id": "neg_cedar_april_incidents",
            "class": "negative",
            "question": (
                "Did Cedar Systems (cust_004) have any incidents opened in April 2024?"
            ),
            "gold_answer": (
                "No. Cedar Systems (cust_004) has no incidents with opened_at in April 2024."
            ),
            "gold_sources": [],
            "story_id": None,
            "must_contain_any": [
                "no",
                "none",
                "zero",
                "0 incidents",
                "did not",
                "no incidents",
            ],
            "must_not_contain": ["inc_1001", "apex logistics"],
            "no_foreign_incident_cites": True,
            "allowed_incident_cites": [inc["_id"] for inc in cedar_incidents],
        },
        {
            "id": "dist_northstar_identity",
            "class": "distributed",
            "question": (
                "Why did Northstar begin experiencing intermittent authentication "
                "failures after recent platform changes?"
            ),
            "gold_answer": (
                "Northstar Payments (cust_012) kept the previous authentication configuration "
                "after the identity platform cutover (mig_ns_identity) set a new OIDC issuer. "
                "Token validation then rejected requests because the issuer did not match."
            ),
            "gold_sources": [
                {"database": RAW_DB, "collection": "tickets", "document_id": "tkt_ns_login"},
                {"database": RAW_DB, "collection": "migrations", "document_id": "mig_ns_identity"},
                {"database": RAW_DB, "collection": "deployments", "document_id": "dep_ns_stale"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_ns_jwt"},
            ],
            "story_id": "identity_oidc",
            "required_evidence_count": 4,
            "must_contain_groups": [
                ["northstar", "cust_012"],
                ["oidc", "identity"],
                ["previous", "stale", "old", "retained"],
                ["issuer", "jwt", "token"],
            ],
        },
        {
            "id": "vk_apex_small",
            "class": "variable_k",
            "question": "What caused Apex's most recent authentication incident?",
            "gold_answer": (
                "The most recent Apex (cust_007) authentication incident (inc_1001) is the May "
                "production auth failure after the SSO cutover; logs show jwt issuer mismatch "
                "(log_1001)."
            ),
            "gold_sources": [
                {"database": RAW_DB, "collection": "incidents", "document_id": "inc_1001"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_1001"},
            ],
            "story_id": "auth_sso",
            "required_evidence_count": 2,
            "must_contain_groups": [
                ["apex", "cust_007"],
                ["auth", "issuer", "401", "sso"],
            ],
        },
        {
            "id": "vk_apex_medium",
            "class": "variable_k",
            "question": (
                "What sequence of events caused Apex's authentication problems during "
                "the May migration?"
            ),
            "gold_answer": (
                "In May, mig_auth_sso changed AUTH_ISSUER to auth-v3. Apex production "
                "deployments dep_apex_fail_1 and dep_apex_fail_2 then failed with AUTH_401; "
                "ticket tkt_1001, incident inc_1001, and logs log_1001/log_1002 document the "
                "jwt issuer mismatch."
            ),
            "gold_sources": [
                {"database": RAW_DB, "collection": "migrations", "document_id": "mig_auth_sso"},
                {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_fail_1"},
                {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_fail_2"},
                {"database": RAW_DB, "collection": "tickets", "document_id": "tkt_1001"},
                {"database": RAW_DB, "collection": "incidents", "document_id": "inc_1001"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_1001"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_1002"},
            ],
            "story_id": "auth_sso",
            "required_evidence_count": 7,
            "must_contain_groups": [
                ["apex", "cust_007"],
                ["mig_auth_sso", "issuer", "auth-v3", "sso"],
                ["auth_401", "401", "fail"],
            ],
        },
        {
            "id": "vk_apex_deep",
            "class": "variable_k",
            "question": (
                "What recurring factors explain Apex's authentication failures across the "
                "last three months, and how did the failure mode evolve?"
            ),
            "gold_answer": (
                "Apex (cust_007) authentication problems evolved: March idle-session timeouts "
                "(SESSION_EXPIRED / cookie max-age), April shortened ACCESS_TOKEN_TTL_SEC "
                "(TOKEN_TTL), then May SSO issuer mismatch after mig_auth_sso (AUTH_401)."
            ),
            "gold_sources": [
                {"database": RAW_DB, "collection": "tickets", "document_id": "tkt_apex_mar"},
                {"database": RAW_DB, "collection": "incidents", "document_id": "inc_apex_mar"},
                {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_mar"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_apex_mar_1"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_apex_mar_2"},
                {"database": RAW_DB, "collection": "tickets", "document_id": "tkt_apex_apr"},
                {"database": RAW_DB, "collection": "incidents", "document_id": "inc_apex_apr"},
                {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_apr"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_apex_apr_1"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_apex_apr_2"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_apex_apr_3"},
                {"database": RAW_DB, "collection": "migrations", "document_id": "mig_auth_sso"},
                {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_fail_1"},
                {"database": RAW_DB, "collection": "deployments", "document_id": "dep_apex_fail_2"},
                {"database": RAW_DB, "collection": "tickets", "document_id": "tkt_1001"},
                {"database": RAW_DB, "collection": "incidents", "document_id": "inc_1001"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_1001"},
                {"database": RAW_DB, "collection": "logs", "document_id": "log_1002"},
            ],
            "story_id": "auth_sso",
            "required_evidence_count": 18,
            "must_contain_groups": [
                ["apex", "cust_007"],
                ["timeout", "idle", "session", "cookie"],
                ["ttl", "token"],
                ["issuer", "sso", "auth_401", "mig_auth_sso"],
            ],
        },
    ]
