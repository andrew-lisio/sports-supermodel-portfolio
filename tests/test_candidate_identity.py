from supermodel import workflow


def test_frozen_model_commit_is_distinct_from_repository_head(monkeypatch) -> None:
    monkeypatch.setenv("SPORTS_SUPERMODEL_MODEL_COMMIT", "model-commit")
    monkeypatch.setenv("SPORTS_SUPERMODEL_GIT_COMMIT", "ui-commit")
    assert workflow._candidate_model_commit() == "model-commit"
    assert workflow._repository_commit() == "ui-commit"
