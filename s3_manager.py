"""
S3 업로드 매니저 (옵션 기능). main 흐름에서는 사용하지 않지만 향후 확장을 위해 유지한다.
"""
import json
from typing import Optional

import boto3
from botocore.exceptions import ClientError


class S3Manager:
    def __init__(
        self,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
        config_key: str = "outline/access.json",
        region: str = "ap-southeast-1",
    ) -> None:
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )
        self.bucket_name = bucket_name
        self.config_key = config_key
        self.region = region

    def upload_access_config(
        self,
        server_ip: str,
        port: int,
        password: str,
        method: str,
    ) -> str:
        config = {
            "server": server_ip,
            "server_port": port,
            "password": password,
            "method": method,
        }
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=self.config_key,
                Body=json.dumps(config, indent=2),
                ContentType="application/json",
            )
            return self.get_public_url()
        except ClientError as e:
            raise RuntimeError(f"S3 업로드 실패: {e}")

    def upload_ss_url(self, ss_url: str) -> str:
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=self.config_key,
                Body=ss_url,
                ContentType="text/plain",
            )
            return self.get_public_url()
        except ClientError as e:
            raise RuntimeError(f"S3 업로드 실패: {e}")

    def get_public_url(self) -> str:
        return f"https://{self.bucket_name}.s3.{self.region}.amazonaws.com/{self.config_key}"

    def test_connection(self) -> bool:
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            return True
        except Exception:
            return False
