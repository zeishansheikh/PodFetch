"""
Unit tests for Google Drive uploader logic, authentication error handling,
subfolder resolution, and duplicate detection.
"""

from unittest.mock import MagicMock, patch
import pytest

from config import AppConfig
from drive_uploader import (
    GoogleDriveAuthError,
    GoogleDriveUploader,
)


def test_missing_credentials_raises_clean_auth_error():
    config = AppConfig(
        google_drive_folder_id="mock_folder_123",
        google_service_account_file=None,
        google_service_account_json=None,
        google_client_id=None,
        google_client_secret=None,
        google_refresh_token=None,
        google_token_file="non_existent_token.json",
    )
    uploader = GoogleDriveUploader(config)
    with pytest.raises(GoogleDriveAuthError) as exc_info:
        uploader.authenticate()
    assert "No valid Google Drive credentials found" in str(exc_info.value)


def test_invalid_service_account_json_raises_clean_auth_error():
    config = AppConfig(
        google_drive_folder_id="mock_folder_123",
        google_service_account_json="{invalid_json: true",
    )
    uploader = GoogleDriveUploader(config)
    with pytest.raises(GoogleDriveAuthError) as exc_info:
        uploader.authenticate()
    assert "Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON" in str(exc_info.value)


def test_check_file_exists_queries_drive():
    config = AppConfig(google_drive_folder_id="parent_123")
    uploader = GoogleDriveUploader(config)

    mock_service = MagicMock()
    mock_files = MagicMock()
    mock_list = MagicMock()
    mock_list.execute.return_value = {"files": [{"id": "drive_file_abc", "name": "test.mp4"}]}
    mock_files.list.return_value = mock_list
    mock_service.files.return_value = mock_files

    uploader._service = mock_service

    found_id = uploader.check_file_exists("test.mp4", "parent_123")
    assert found_id == "drive_file_abc"
    mock_files.list.assert_called_once()
    query_arg = mock_files.list.call_args[1]["q"]
    assert "'parent_123' in parents" in query_arg
    assert "name = 'test.mp4'" in query_arg


def test_date_subfolder_creation():
    config = AppConfig(google_drive_folder_id="parent_123")
    uploader = GoogleDriveUploader(config)

    mock_service = MagicMock()
    mock_files = MagicMock()

    # First call to list returns no existing subfolder
    mock_list = MagicMock()
    mock_list.execute.return_value = {"files": []}
    mock_files.list.return_value = mock_list

    # Call to create returns new folder ID
    mock_create = MagicMock()
    mock_create.execute.return_value = {"id": "subfolder_456", "name": "2026-10-08"}
    mock_files.create.return_value = mock_create

    mock_service.files.return_value = mock_files
    uploader._service = mock_service

    folder_id, folder_name = uploader.get_or_create_date_subfolder("parent_123", date_str="2026-10-08")
    assert folder_id == "subfolder_456"
    assert folder_name == "2026-10-08"
    mock_files.create.assert_called_once()
