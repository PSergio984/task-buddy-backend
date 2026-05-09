import logging
from functools import lru_cache

import b2sdk.v2 as b2

from app.config import config

logger = logging.getLogger(__name__)


@lru_cache
def b2_api():
    info = b2.InMemoryAccountInfo()
    b2_api = b2.B2Api(info)  # type: ignore

    b2_api.authorize_account("production", config.B2_KEY_ID, config.B2_APPLICATION_KEY)
    return b2_api


@lru_cache
def b2_get_bucket(api: b2.B2Api):
    if not config.B2_BUCKET_NAME:
        raise ValueError("B2_BUCKET_NAME is not configured")
    return api.get_bucket_by_name(config.B2_BUCKET_NAME)


def b2_upload_file(local_file: str, file_name: str) -> str:
    api = b2_api()
    logger.debug(f"Uploading {local_file} to B2 as {file_name}")

    # Uploading the file to the specified bucket
    uploaded_file = b2_get_bucket(api).upload_local_file(local_file=local_file, file_name=file_name)

    # Generating the public download URL
    download_url = api.get_download_url_for_fileid(uploaded_file.id_)

    logger.debug(f"Uploaded {local_file} to B2 successfully and got download URL {download_url}")

    return download_url
