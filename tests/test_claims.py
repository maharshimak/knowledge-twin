from knowledge_twin.claims import Claim, ClaimLedger


def test_claim_ledger_detects_conflicting_evidence():
    ledger = ClaimLedger()
    ledger.add(Claim("Project A", "status", "active", "source 1", 0.9))
    ledger.add(Claim("Project A", "status", "paused", "source 2", 0.8))

    conflicts = ledger.conflicts()
    assert len(conflicts) == 1
    assert set(conflicts[0].objects) == {"active", "paused"}


def test_best_supported_aggregates_independent_evidence():
    ledger = ClaimLedger()
    ledger.add(Claim("A", "located_in", "Paris", "s1", 0.6))
    ledger.add(Claim("A", "located_in", "Paris", "s2", 0.6))
    ledger.add(Claim("A", "located_in", "Lyon", "s3", 0.9))

    assert ledger.best_supported("A", "located_in").object == "Paris"



def test_multi_valued_predicate_is_not_a_conflict():
    ledger = ClaimLedger()
    ledger.add(Claim("Maharshi", "has_skill", "Python", "source 1", 0.9))
    ledger.add(Claim("Maharshi", "has_skill", "Java", "source 2", 0.9))

    assert ledger.conflicts() == ()


def test_single_valued_claim_change_over_time_is_not_a_conflict():
    ledger = ClaimLedger()
    ledger.add(
        Claim(
            "Project A",
            "status",
            "active",
            "source 1",
            0.9,
            observed_at="2026-01-01",
        )
    )
    ledger.add(
        Claim(
            "Project A",
            "status",
            "paused",
            "source 2",
            0.9,
            observed_at="2026-02-01",
        )
    )

    assert ledger.conflicts() == ()


def test_single_valued_claims_at_same_time_can_conflict():
    ledger = ClaimLedger()
    ledger.add(
        Claim(
            "Project A",
            "status",
            "active",
            "source 1",
            0.9,
            observed_at="2026-01-01",
        )
    )
    ledger.add(
        Claim(
            "Project A",
            "status",
            "paused",
            "source 2",
            0.9,
            observed_at="2026-01-01",
        )
    )

    conflicts = ledger.conflicts()
    assert len(conflicts) == 1
    assert set(conflicts[0].objects) == {"active", "paused"}
