from app.eval.ir_metrics import mean_scores, ndcg_at_k, precision_at_k, recall_at_k, score_ranking


def test_ir_metrics_perfect_ranking():
    gold = ["a", "b"]
    ranked = ["a", "b", "c"]
    assert recall_at_k(ranked, gold, 2) == 1.0
    assert precision_at_k(ranked, gold, 2) == 1.0
    scores = score_ranking(ranked, gold, 2)
    assert scores["recall"] == 1.0
    assert scores["hits"] == 2


def test_ir_metrics_misses_and_ndcg():
    gold = ["a", "b"]
    ranked = ["x", "a"]
    assert recall_at_k(ranked, gold, 2) == 0.5
    assert ndcg_at_k(["a", "b"], gold, 2) > ndcg_at_k(["x", "a"], gold, 2)
    mean = mean_scores([score_ranking(ranked, gold, 2)])
    assert 0.4 < mean["recall"] < 0.6
