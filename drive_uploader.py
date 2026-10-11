"""
Google Drive API uploader module.
Supports Service Account and OAuth 2.0 authentication for unattended cloud runners,
date-based subfolder structuring, duplicate prevention, and resumable chunked uploads.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as OAuthCredentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config import AppConfig
from logger import get_logger

logger = get_logger("drive_uploader")

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]


class GoogleDriveAuthError(Exception):
    """Raised when Google Drive credentials cannot be loaded or authenticated."""
    pass


class GoogleDriveUploadError(Exception):
    """Raised when file upload to Google Drive fails."""
    pass


class GoogleDriveUploader:
    """Handles authentication, folder structure navigation, and resumable uploads to Google Drive."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._service: Optional[Resource] = None

    def authenticate(self) -> Resource:
        """Authenticate with Google Drive API using configured credentials.

        Returns:
            Authenticated Google Drive Resource.

        Raises:
            GoogleDriveAuthError: If authentication fails or credentials are missing.
        """
        if self._service is not None:
            return self._service

        creds = None

        # 1. Service Account from file
        if self.config.google_service_account_file:
            sa_path = Path(self.config.google_service_account_file)
            if sa_path.exists():
                try:
                    logger.info(f"Authenticating via Service Account file: {sa_path}")
                    creds = service_account.Credentials.from_service_account_file(
                        str(sa_path), scopes=DRIVE_SCOPES
                    )
                except Exception as e:
                    raise GoogleDriveAuthError(f"Failed to load Service Account file {sa_path}: {e}")
            else:
                logger.warning(f"Specified service account file {sa_path} not found.")

        # 2. Service Account from raw JSON environment variable
        if creds is None and self.config.google_service_account_json:
            try:
                logger.info("Authenticating via Service Account JSON environment variable")
                sa_data = json.loads(self.config.google_service_account_json)
                creds = service_account.Credentials.from_service_account_info(
                    sa_data, scopes=DRIVE_SCOPES
                )
            except Exception as e:
                raise GoogleDriveAuthError(f"Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON: {e}")

        # 3. OAuth 2.0 Refresh Token (Ideal for unattended personal Google Drive)
        if (
            creds is None
            and self.config.google_client_id
            and self.config.google_client_secret
            and self.config.google_refresh_token
        ):
            try:
                logger.info("Authenticating via OAuth 2.0 Refresh Token")
                creds = OAuthCredentials(
                    token=None,
                    refresh_token=self.config.google_refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=self.config.google_client_id,
                    client_secret=self.config.google_client_secret,
                    scopes=DRIVE_SCOPES,
                )
                creds.refresh(Request())
            except Exception as e:
                raise GoogleDriveAuthError(f"Failed to refresh OAuth token: {e}")

        # 4. Token / credentials file
        token_candidate = self.config.google_token_file or "token.json"
        if creds is None and Path(token_candidate).exists():
            try:
                logger.info(f"Authenticating via authorized user token file: {token_candidate}")
                creds = OAuthCredentials.from_authorized_user_file(
                    token_candidate, scopes=DRIVE_SCOPES
                )
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
            except Exception as e:
                raise GoogleDriveAuthError(f"Failed to load token file {token_candidate}: {e}")

        if creds is None:
            raise GoogleDriveAuthError(
                "No valid Google Drive credentials found. Please configure either:\n"
                "  - GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON\n"
                "  - GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN\n"
                "  - GOOGLE_TOKEN_FILE\n"
                "See README.md for instructions."
            )

        try:
            self._service = build("drive", "v3", credentials=creds, cache_discovery=False)
            logger.info("Google Drive API client initialized successfully.")
            return self._service
        except Exception as e:
            raise GoogleDriveAuthError(f"Failed to build Google Drive API service: {e}")

    def get_or_create_subfolder(
        self, parent_folder_id: str, folder_name: str
    ) -> Tuple[str, str]:
        """Find or create a subfolder with the specified name inside a parent folder.

        Args:
            parent_folder_id: Google Drive ID of parent folder.
            folder_name: Subfolder name to find or create.

        Returns:
            Tuple of (subfolder_id, folder_name).
        """
        service = self.authenticate()
        safe_name = folder_name.replace("\\", "\\\\").replace("'", "\\'")

        query = (
            f"'{parent_folder_id}' in parents and "
            f"name = '{safe_name}' and "
            f"mimeType = 'application/vnd.google-apps.folder' and "
            f"trashed = false"
        )
        response = (
            service.files()
            .list(q=query, spaces="drive", fields="files(id, name)")
            .execute()
        )
        files = response.get("files", [])

        if files:
            folder_id = files[0]["id"]
            logger.debug(f"Found existing subfolder '{folder_name}' (ID: {folder_id})")
            return folder_id, folder_name

        folder_metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        }
        folder = (
            service.files()
            .create(body=folder_metadata, fields="id, name")
            .execute()
        )
        folder_id = folder.get("id")
        logger.info(f"Created new subfolder '{folder_name}' (ID: {folder_id})")
        return folder_id, folder_name

    def get_or_create_date_subfolder(
        self, parent_folder_id: str, date_str: Optional[str] = None
    ) -> Tuple[str, str]:
        """Find or create a subfolder for the specified date (e.g. '2026-10-08').

        Args:
            parent_folder_id: Google Drive ID of parent folder.
            date_str: Date folder name in YYYY-MM-DD format (defaults to current UTC date).

        Returns:
            Tuple of (subfolder_id, subfolder_name).
        """
        if not date_str:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self.get_or_create_subfolder(parent_folder_id, date_str)

    def check_file_exists(
        self, filename: str, target_folder_id: str
    ) -> Optional[str]:
        """Check if file with identical name already exists in destination folder.

        Returns:
            Existing Drive file ID if found, otherwise None.
        """
        service = self.authenticate()
        # Escape single quotes in filename for Google Drive query syntax
        safe_name = filename.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"'{target_folder_id}' in parents and "
            f"name = '{safe_name}' and "
            f"trashed = false"
        )
        try:
            response = (
                service.files()
                .list(q=query, spaces="drive", fields="files(id, name, size)")
                .execute()
            )
            files = response.get("files", [])
            if files:
                existing_id = files[0]["id"]
                logger.info(
                    f"File '{filename}' already exists in Google Drive (ID: {existing_id})"
                )
                return existing_id
        except HttpError as e:
            logger.warning(f"Error checking file existence in Drive: {e}")

        return None

    def upload_file(
        self,
        file_path: Path,
        custom_filename: Optional[str] = None,
        platform: Optional[str] = None,
        mimetype: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Perform chunked resumable upload of any media or metadata file to Google Drive.

        Args:
            file_path: Local path to the file.
            custom_filename: Optional sanitized filename for Drive.
            platform: Optional platform ('instagram', 'pinterest', 'youtube') to organize into dedicated folder.
            mimetype: Optional MIME type (auto-detected if None).
            description: Optional file description metadata.

        Returns:
            Tuple of (drive_file_id, drive_path_string).

        Raises:
            GoogleDriveUploadError: If upload fails.
        """
        if not file_path.exists():
            raise GoogleDriveUploadError(f"Local file does not exist: {file_path}")

        service = self.authenticate()
        parent_folder_id = self.config.google_drive_folder_id
        filename = custom_filename or file_path.name
        file_size = file_path.stat().st_size

        # Resolve destination folder hierarchy
        current_target_id = parent_folder_id
        display_parts = [parent_folder_id]

        # 1. Platform-specific subfolder (e.g. 'instagram', 'pinterest', 'youtube') to prevent mixing
        effective_platform = platform
        if not effective_platform:
            fname_lower = (custom_filename or file_path.name).lower()
            if "instagram" in fname_lower:
                effective_platform = "instagram"
            elif "pinterest" in fname_lower:
                effective_platform = "pinterest"
            elif "youtube" in fname_lower:
                effective_platform = "youtube"

        if effective_platform:
            platform_folder_name = effective_platform.strip().lower()
            current_target_id, plat_name = self.get_or_create_subfolder(
                current_target_id, platform_folder_name
            )
            display_parts.append(plat_name)

        # 2. Date subfolder inside destination folder
        if self.config.use_date_subfolders:
            current_target_id, date_folder_name = self.get_or_create_date_subfolder(
                current_target_id
            )
            display_parts.append(date_folder_name)

        target_folder_id = current_target_id
        display_parts.append(filename)
        drive_display_path = "/".join(display_parts)

        # Duplicate check inside destination folder
        existing_id = self.check_file_exists(filename, target_folder_id)
        if existing_id:
            logger.info(f"Skipping upload: file already present in Drive as {existing_id}")
            return existing_id, drive_display_path

        # Determine appropriate MIME type
        if not mimetype:
            suffix = file_path.suffix.lower()
            if suffix == ".mp3":
                resolved_mimetype = "audio/mpeg"
            elif suffix in (".m4a", ".aac"):
                resolved_mimetype = "audio/mp4"
            elif suffix == ".wav":
                resolved_mimetype = "audio/wav"
            elif suffix == ".json":
                resolved_mimetype = "application/json"
            elif suffix == ".mp4":
                resolved_mimetype = "video/mp4"
            else:
                resolved_mimetype = "application/octet-stream"
        else:
            resolved_mimetype = mimetype

        # 10 MB upload chunk size for reliability on cloud servers
        chunk_size = 10 * 1024 * 1024
        media = MediaFileUpload(
            str(file_path),
            mimetype=resolved_mimetype,
            resumable=True,
            chunksize=chunk_size,
        )

        file_metadata = {
            "name": filename,
            "parents": [target_folder_id],
            "description": description or "Automated media download",
        }

        logger.info(
            f"Starting Drive upload for '{filename}' "
            f"({file_size / (1024 * 1024):.2f} MB, {resolved_mimetype}) -> {drive_display_path}"
        )

        request = service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, size, webViewLink",
        )

        response = None
        attempt = 0
        last_progress_pct = -1

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    progress_pct = int(status.progress() * 100)
                    if progress_pct != last_progress_pct and progress_pct % 20 == 0:
                        logger.info(f"Uploading '{filename}': {progress_pct}% completed")
                        last_progress_pct = progress_pct
            except (HttpError, OSError, Exception) as err:
                attempt += 1
                if attempt > self.config.max_retries:
                    raise GoogleDriveUploadError(
                        f"Failed uploading {filename} after {self.config.max_retries} chunk retries: {err}"
                    )
                delay = self.config.backoff_factor ** attempt
                logger.warning(
                    f"Upload chunk error ({err}). Retrying attempt {attempt} in {delay:.1f}s..."
                )
                time.sleep(delay)

        uploaded_id = response.get("id")
        if not uploaded_id:
            raise GoogleDriveUploadError("Drive API response did not contain file ID")

        logger.info(f"Successfully uploaded to Google Drive! File ID: {uploaded_id}")
        return uploaded_id, drive_display_path

    def upload_video(
        self,
        file_path: Path,
        custom_filename: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Perform chunked resumable upload of a video file to Google Drive (backwards compatibility)."""
        return self.upload_file(
            file_path=file_path,
            custom_filename=custom_filename,
            platform=platform,
            mimetype="video/mp4",
            description="Automated podcast video download",
        )
