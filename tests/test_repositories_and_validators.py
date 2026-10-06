"""
tests/test_repositories_and_validators.py
==========================================
Unit tests for the new repository wrappers (Task 3) and input validators
(Task 5) added in the production-readiness pass.
"""

import pytest


class TestUserRepository:
    def test_create_and_get_by_username(self, app_module):
        from repositories.user_repository import UserRepository

        repo = UserRepository()
        repo.create("repouser", "hashed_password_value")
        user = repo.get_by_username("repouser")
        assert user is not None
        assert user["username"] == "repouser"

    def test_target_role_roundtrip(self, app_module, test_user):
        from repositories.user_repository import UserRepository

        repo = UserRepository()
        assert repo.get_target_role(str(test_user["id"])) is None
        repo.set_target_role(str(test_user["id"]), "ML Engineer")
        assert repo.get_target_role(str(test_user["id"])) == "ML Engineer"


class TestHistoryRepository:
    def test_add_and_retrieve_activity(self, app_module, test_user):
        from repositories.history_repository import HistoryRepository

        repo = HistoryRepository()
        repo.add_activity(
            user_id=str(test_user["id"]),
            input_activity="Managed a team budget",
            mapped_skill="Budget Management",
            onet_category="Finance",
            leadership_category="Leadership",
            skill_magnitude=60,
            market_value="Medium",
            career_equivalency="Matches Financial Analyst",
            leadership_index=55,
            employability_score=58,
            skills_mapped=["Budget Management"],
        )
        activities = repo.get_all_for_user(str(test_user["id"]))
        assert len(activities) == 1
        assert activities[0]["mapped_skill"] == "Budget Management"

    def test_aggregated_metrics_shape(self, app_module, test_user):
        from repositories.history_repository import HistoryRepository

        repo = HistoryRepository()
        metrics = repo.get_aggregated_metrics(str(test_user["id"]))
        assert "total_activities" in metrics


class TestCopilotRepository:
    def test_message_roundtrip_and_clear(self, app_module, test_user):
        from repositories.copilot_repository import CopilotRepository

        repo = CopilotRepository()
        repo.add_message(str(test_user["id"]), "user", "hello")
        repo.add_message(str(test_user["id"]), "assistant", "hi there")
        history = repo.get_history(str(test_user["id"]))
        assert [m["role"] for m in history] == ["user", "assistant"]
        repo.clear(str(test_user["id"]))
        assert repo.get_history(str(test_user["id"])) == []


class TestOpportunityRepository:
    def test_add_get_unread_count_and_mark_read(self, app_module, test_user):
        from repositories.opportunity_repository import OpportunityRepository

        repo = OpportunityRepository()
        repo.add(str(test_user["id"]), "A new opportunity", "/")
        assert repo.get_unread_count(str(test_user["id"])) == 1
        repo.mark_all_read(str(test_user["id"]))
        assert repo.get_unread_count(str(test_user["id"])) == 0


class TestValidators:
    def test_require_fields_passes_when_all_present(self):
        from utils.validators import require_fields

        require_fields({"a": "1", "b": "2"}, ["a", "b"])  # should not raise

    def test_require_fields_lists_all_missing_at_once(self):
        from utils.validators import require_fields, ValidationError

        with pytest.raises(ValidationError) as exc_info:
            require_fields({"a": "1"}, ["a", "b", "c"])
        assert "b" in str(exc_info.value)
        assert "c" in str(exc_info.value)

    def test_validate_string_length_trims_and_checks_bounds(self):
        from utils.validators import validate_string_length, ValidationError

        assert validate_string_length("  hello  ", "field", max_length=10) == "hello"
        with pytest.raises(ValidationError):
            validate_string_length("this is way too long", "field", max_length=5)
        with pytest.raises(ValidationError):
            validate_string_length("", "field", max_length=10, min_length=1)

    def test_validate_file_upload_rejects_bad_extension(self):
        from utils.validators import validate_file_upload, ValidationError

        with pytest.raises(ValidationError):
            validate_file_upload("virus.exe", b"some bytes")

    def test_validate_file_upload_rejects_oversized_file(self):
        from utils.validators import validate_file_upload, ValidationError

        with pytest.raises(ValidationError):
            validate_file_upload("resume.pdf", b"x" * (9 * 1024 * 1024))

    def test_validate_file_upload_accepts_valid_file(self):
        from utils.validators import validate_file_upload

        validate_file_upload("resume.pdf", b"%PDF-1.4 fake but non-empty")  # should not raise

    def test_sanitize_plain_text_escapes_html(self):
        from utils.validators import sanitize_plain_text

        assert sanitize_plain_text("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"

    def test_validate_username_accepts_valid(self):
        from utils.validators import validate_username

        assert validate_username("valid_user-1") == "valid_user-1"

    def test_validate_username_rejects_too_short(self):
        from utils.validators import validate_username, ValidationError

        with pytest.raises(ValidationError):
            validate_username("ab")
