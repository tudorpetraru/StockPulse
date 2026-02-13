from app.services.prediction_service import PredictionSnapshotService


def test_composite_score_clamps_to_zero_and_one() -> None:
    assert PredictionSnapshotService.composite_score(0.0, 0.0, 10.0) == 0.0
    assert PredictionSnapshotService.composite_score(1.0, 1.0, 0.0) == 1.0


def test_predicted_and_actual_return() -> None:
    predicted = PredictionSnapshotService.compute_predicted_return(120.0, 100.0)
    actual = PredictionSnapshotService.compute_actual_return(110.0, 100.0)

    assert round(predicted, 4) == 0.2
    assert round(actual, 4) == 0.1


def test_directional_correctness() -> None:
    assert PredictionSnapshotService.is_directionally_correct(0.2, 0.1) is True
    assert PredictionSnapshotService.is_directionally_correct(-0.2, -0.1) is True
    assert PredictionSnapshotService.is_directionally_correct(0.2, -0.1) is False
