"""
AWS Lightsail Static IP 교체 매니저.
인스턴스 IP를 Static IP 분리 -> 삭제 -> 재할당 -> 재연결 순서로 교체한다.
"""
import boto3
from botocore.exceptions import ClientError
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable


@dataclass
class RotationResult:
    success: bool
    old_ip: str
    new_ip: str
    new_static_ip_name: str
    error: Optional[str] = None


class AWSOperationError(Exception):
    def __init__(self, operation: str, message: str, original_error: Optional[Exception] = None) -> None:
        self.operation = operation
        self.message = message
        self.original_error = original_error
        super().__init__(f"AWS {operation} 실패: {message}")


class AWSManager:
    def __init__(self, access_key_id: str, secret_access_key: str, region: str = "ap-southeast-1") -> None:
        self.region = region
        self.client = boto3.client(
            "lightsail",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )

    def test_connection(self) -> bool:
        try:
            self.client.get_static_ips()
            return True
        except Exception:
            return False

    def get_instance_info(self, instance_name: str) -> dict:
        try:
            resp = self.client.get_instance(instanceName=instance_name)
            inst = resp.get("instance", {})
            return {
                "name": inst.get("name", ""),
                "state": inst.get("state", {}).get("name", ""),
                "public_ip": inst.get("publicIpAddress", ""),
                "blueprint_id": inst.get("blueprintId", ""),
                "bundle_id": inst.get("bundleId", ""),
                "region": inst.get("location", {}).get("regionName", ""),
            }
        except ClientError as e:
            raise AWSOperationError("GetInstance", str(e), e)

    def get_static_ips(self) -> list:
        try:
            resp = self.client.get_static_ips()
            result = []
            for ip in resp.get("staticIps", []):
                result.append({
                    "name": ip.get("name", ""),
                    "ip_address": ip.get("ipAddress", ""),
                    "is_attached": ip.get("isAttached", False),
                    "attached_to": ip.get("attachedTo", ""),
                    "region": ip.get("location", {}).get("regionName", ""),
                })
            return result
        except ClientError as e:
            raise AWSOperationError("GetStaticIps", str(e), e)

    def get_current_static_ip(self, instance_name: str) -> Optional[dict]:
        ips = self.get_static_ips()
        for ip in ips:
            if ip.get("is_attached") and ip.get("attached_to") == instance_name:
                return ip
        return None

    def detach_static_ip(self, static_ip_name: str) -> bool:
        try:
            self.client.detach_static_ip(staticIpName=static_ip_name)
            return True
        except ClientError as e:
            raise AWSOperationError("DetachStaticIp", str(e), e)

    def release_static_ip(self, static_ip_name: str) -> bool:
        try:
            self.client.release_static_ip(staticIpName=static_ip_name)
            return True
        except ClientError as e:
            raise AWSOperationError("ReleaseStaticIp", str(e), e)

    def allocate_static_ip(self, static_ip_name: str) -> str:
        try:
            self.client.allocate_static_ip(staticIpName=static_ip_name)
            resp = self.client.get_static_ip(staticIpName=static_ip_name)
            return resp.get("staticIp", {}).get("ipAddress", "")
        except ClientError as e:
            raise AWSOperationError("AllocateStaticIp", str(e), e)

    def attach_static_ip(self, static_ip_name: str, instance_name: str) -> bool:
        try:
            self.client.attach_static_ip(
                staticIpName=static_ip_name,
                instanceName=instance_name,
            )
            return True
        except ClientError as e:
            raise AWSOperationError("AttachStaticIp", str(e), e)

    @staticmethod
    def generate_static_ip_name(prefix: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{prefix}-{timestamp}"

    def rotate_ip(
        self,
        instance_name: str,
        current_static_ip_name: str = "",
        ip_name_prefix: str = "OutlineVPN-IP",
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> RotationResult:
        old_ip = ""
        new_ip = ""
        new_name = ""

        def report(msg: str, pct: int) -> None:
            if progress_callback:
                progress_callback(msg, pct)

        try:
            current = None
            if current_static_ip_name:
                # 사용자가 알려준 Static IP 이름이 있다면 그 항목을 확인
                for ip in self.get_static_ips():
                    if ip.get("name") == current_static_ip_name:
                        current = ip
                        break
            if current is None:
                current = self.get_current_static_ip(instance_name)

            if current:
                old_ip = current.get("ip_address", "")
                current_static_ip_name = current.get("name", current_static_ip_name)

                report("기존 Static IP 분리 중...", 10)
                self.detach_static_ip(current_static_ip_name)
                report("기존 Static IP 분리 완료", 25)

                report("기존 Static IP 삭제 중...", 30)
                self.release_static_ip(current_static_ip_name)
                report("기존 Static IP 삭제 완료", 45)

            new_name = self.generate_static_ip_name(ip_name_prefix)
            report("새 Static IP 할당 중...", 50)
            new_ip = self.allocate_static_ip(new_name)
            report(f"새 IP 할당 완료: {new_ip}", 70)

            report("새 Static IP 인스턴스에 연결 중...", 75)
            self.attach_static_ip(new_name, instance_name)
            report("연결 완료!", 90)

            return RotationResult(
                success=True,
                old_ip=old_ip,
                new_ip=new_ip,
                new_static_ip_name=new_name,
            )
        except AWSOperationError as e:
            return RotationResult(
                success=False,
                old_ip=old_ip,
                new_ip=new_ip,
                new_static_ip_name=new_name,
                error=str(e),
            )
        except Exception as e:
            return RotationResult(
                success=False,
                old_ip=old_ip,
                new_ip=new_ip,
                new_static_ip_name=new_name,
                error=f"예상치 못한 오류: {e}",
            )
