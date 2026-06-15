"""Dify document sync helpers"""
import logging

logger = logging.getLogger(__name__)


class DifyInnerApiReader:
    def __init__(self, api_key: str):
        self.api_key = api_key


async def sync_dify_documents_to_cloudrag(conn, reader: DifyInnerApiReader, uploaded_by: str):
    pass
