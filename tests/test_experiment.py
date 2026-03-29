"""Tests for the A/B experimentation framework."""
import json
import os
import tempfile
import shutil
import pytest

from src.experiment import (
    Variant,
    Experiment,
    ExperimentManager,
    assign_variant,
)


# ---------------------------------------------------------------------------
# assign_variant: deterministic hashing
# ---------------------------------------------------------------------------

class TestAssignVariant:
    def setup_method(self):
        self.variants = [
            Variant(name="control", description="", traffic_pct=0.5),
            Variant(name="treatment", description="", traffic_pct=0.5),
        ]

    def test_deterministic(self):
        """Same (experiment, user) always returns the same variant."""
        v1 = assign_variant("exp1", "user42", self.variants)
        v2 = assign_variant("exp1", "user42", self.variants)
        assert v1.name == v2.name

    def test_different_users_get_both_variants(self):
        """Over many users, both variants should be assigned."""
        names = set()
        for i in range(200):
            v = assign_variant("exp1", str(i), self.variants)
            names.add(v.name)
        assert names == {"control", "treatment"}

    def test_different_experiments_can_differ(self):
        """Changing experiment_id can change the assignment for the same user."""
        results = set()
        for exp_id in [f"exp_{i}" for i in range(50)]:
            v = assign_variant(exp_id, "user1", self.variants)
            results.add(v.name)
        # With 50 experiments, we should see both variants at least once
        assert len(results) == 2

    def test_uneven_split(self):
        """90/10 split should assign ~90% to the majority variant."""
        variants = [
            Variant(name="A", description="", traffic_pct=0.9),
            Variant(name="B", description="", traffic_pct=0.1),
        ]
        counts = {"A": 0, "B": 0}
        for i in range(1000):
            v = assign_variant("exp", str(i), variants)
            counts[v.name] += 1
        assert counts["A"] > 800  # should be ~900
        assert counts["B"] > 50   # should be ~100

    def test_three_variants(self):
        """Supports more than two variants."""
        variants = [
            Variant(name="A", description="", traffic_pct=0.33),
            Variant(name="B", description="", traffic_pct=0.34),
            Variant(name="C", description="", traffic_pct=0.33),
        ]
        names = set()
        for i in range(500):
            v = assign_variant("exp", str(i), variants)
            names.add(v.name)
        assert names == {"A", "B", "C"}


# ---------------------------------------------------------------------------
# Experiment dataclass
# ---------------------------------------------------------------------------

class TestExperiment:
    def test_from_dict_variants(self):
        exp = Experiment(
            id="test",
            name="Test",
            description="desc",
            variants=[
                {"name": "a", "description": "d", "traffic_pct": 0.5},
                {"name": "b", "description": "d", "traffic_pct": 0.5},
            ],
        )
        assert len(exp.variants) == 2
        assert isinstance(exp.variants[0], Variant)
        assert exp.variants[0].name == "a"

    def test_default_timestamps(self):
        exp = Experiment(id="x", name="X", description="", variants=[])
        assert exp.created_at != ""
        assert exp.started_at != ""


# ---------------------------------------------------------------------------
# ExperimentManager: load, save, assign
# ---------------------------------------------------------------------------

class TestExperimentManager:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "logs"), exist_ok=True)
        # Write a test experiment config
        config = {
            "id": "test_exp",
            "name": "Test Experiment",
            "description": "For testing",
            "status": "active",
            "variants": [
                {"name": "control", "description": "c", "traffic_pct": 0.5},
                {"name": "treatment", "description": "t", "traffic_pct": 0.5},
            ],
        }
        with open(os.path.join(self.tmpdir, "test_exp.json"), "w") as f:
            json.dump(config, f)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_experiments(self):
        mgr = ExperimentManager(experiments_dir=self.tmpdir)
        assert len(mgr.get_active_experiments()) == 1
        exp = mgr.get_experiment("test_exp")
        assert exp is not None
        assert exp.name == "Test Experiment"

    def test_get_variant_for_user(self):
        mgr = ExperimentManager(experiments_dir=self.tmpdir)
        v = mgr.get_variant_for_user("test_exp", "user123")
        assert v is not None
        assert v.name in {"control", "treatment"}

    def test_get_variant_nonexistent_experiment(self):
        mgr = ExperimentManager(experiments_dir=self.tmpdir)
        v = mgr.get_variant_for_user("no_such_exp", "user1")
        assert v is None

    def test_get_all_assignments(self):
        mgr = ExperimentManager(experiments_dir=self.tmpdir)
        assignments = mgr.get_all_assignments("user1")
        assert "test_exp" in assignments
        assert assignments["test_exp"] in {"control", "treatment"}

    def test_save_experiment(self):
        mgr = ExperimentManager(experiments_dir=self.tmpdir)
        new_exp = Experiment(
            id="new_exp",
            name="New",
            description="desc",
            variants=[
                Variant(name="a", description="", traffic_pct=1.0),
            ],
        )
        mgr.save_experiment(new_exp)
        assert os.path.exists(os.path.join(self.tmpdir, "new_exp.json"))
        assert mgr.get_experiment("new_exp") is not None

    def test_log_assignment(self):
        mgr = ExperimentManager(experiments_dir=self.tmpdir)
        mgr.log_assignment("test_exp", "user1", "control", ["movie1", "movie2"])
        log_path = os.path.join(self.tmpdir, "logs", "test_exp.jsonl")
        assert os.path.exists(log_path)
        with open(log_path) as f:
            record = json.loads(f.readline())
        assert record["user_id"] == "user1"
        assert record["variant"] == "control"
        assert record["recommendations"] == ["movie1", "movie2"]

    def test_paused_experiment_not_active(self):
        config = {
            "id": "paused_exp",
            "name": "Paused",
            "description": "",
            "status": "paused",
            "variants": [
                {"name": "a", "description": "", "traffic_pct": 1.0},
            ],
        }
        with open(os.path.join(self.tmpdir, "paused_exp.json"), "w") as f:
            json.dump(config, f)
        mgr = ExperimentManager(experiments_dir=self.tmpdir)
        active = mgr.get_active_experiments()
        assert all(e.id != "paused_exp" for e in active)
        assert mgr.get_variant_for_user("paused_exp", "user1") is None


# ---------------------------------------------------------------------------
# Statistical tests (from analysis script)
# ---------------------------------------------------------------------------

class TestStatisticalTests:
    def test_two_proportion_z_test_identical(self):
        from scripts.experiment_analysis import two_proportion_z_test
        z, p = two_proportion_z_test(50, 100, 50, 100)
        assert abs(z) < 0.01
        assert p > 0.9

    def test_two_proportion_z_test_different(self):
        from scripts.experiment_analysis import two_proportion_z_test
        z, p = two_proportion_z_test(90, 100, 10, 100)
        assert abs(z) > 2.0
        assert p < 0.05

    def test_welch_t_test_identical(self):
        from scripts.experiment_analysis import welch_t_test
        a = [3.0, 3.1, 2.9, 3.0, 3.05]
        t, p = welch_t_test(a, a)
        assert abs(t) < 0.01
        assert p > 0.9

    def test_welch_t_test_different(self):
        from scripts.experiment_analysis import welch_t_test
        import numpy as np
        rng = np.random.RandomState(42)
        a = rng.normal(1.0, 0.5, 50).tolist()
        b = rng.normal(5.0, 0.5, 50).tolist()
        t, p = welch_t_test(a, b)
        assert abs(t) > 2.0
        assert p < 0.05

    def test_confidence_interval_proportion(self):
        from scripts.experiment_analysis import confidence_interval_proportion
        p, lo, hi = confidence_interval_proportion(50, 100)
        assert 0.4 < lo < 0.5
        assert 0.5 < hi < 0.6
        assert abs(p - 0.5) < 0.01

    def test_confidence_interval_mean(self):
        from scripts.experiment_analysis import confidence_interval_mean
        vals = [10.0] * 100
        mean, lo, hi = confidence_interval_mean(vals)
        assert mean == 10.0
        assert lo == 10.0
        assert hi == 10.0

    def test_empty_inputs(self):
        from scripts.experiment_analysis import (
            two_proportion_z_test, welch_t_test,
            confidence_interval_proportion, confidence_interval_mean,
        )
        _, p1 = two_proportion_z_test(0, 0, 0, 0)
        assert p1 == 1.0
        _, p2 = welch_t_test([], [])
        assert p2 == 1.0
        p, lo, hi = confidence_interval_proportion(0, 0)
        assert p == 0.0
        m, mlo, mhi = confidence_interval_mean([])
        assert m == 0.0
