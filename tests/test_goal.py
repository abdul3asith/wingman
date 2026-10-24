import pytest

from app.memory.build import GOAL_LINK_MIN, cosine, goal_link, profile_text
from app.memory.extract import MOCK_JORDAN


def test_cosine():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 2.0]) == pytest.approx(0.0)
    assert cosine([1.0, 1.0], [-1.0, -1.0]) == pytest.approx(-1.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0  # zero vector: no division by zero


def test_goal_link_threshold_is_inclusive():
    assert GOAL_LINK_MIN == 0.5
    assert goal_link(0.5) and goal_link(0.9)
    assert not goal_link(0.49) and not goal_link(0.0)


def test_profile_text_carries_job_facts():
    text = profile_text(MOCK_JORDAN)
    assert "hiring" in text and "Technical Recruiter at Lattice Compute" in text
    assert "Python and Go" in text
