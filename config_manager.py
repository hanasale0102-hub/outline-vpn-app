"""
설정 및 이력 영구 저장 매니저.
Android 환경에서는 앱 전용 저장소(app_storage_path)에, 그 외에는 스크립트와 같은 디렉터리에 저장한다.
"""
import json
import os
from datetime import datetime
from typing import Optional


DEFAULT_CONFIG = {
    "aws": {
        "access_key_id": "",
        "secret_access_key": "",
        "region": "ap-southeast-1",
        "instance_name": "",
        "static_ip_prefix": "OutlineVPN-IP",
    },
    "outline": {
        "api_url": "",
        "cert_sha256": "",
    },
    "current_ip": "",
    "current_static_ip_name": "",
}


AVAILABLE_REGIONS = [
    {"id": "ap-southeast-1", "name": "싱가포르"},
    {"id": "ap-northeast-1", "name": "도쿄 (일본)"},
    {"id": "ap-northeast-2", "name": "서울 (한국)"},
    {"id": "ap-south-1", "name": "뭄바이 (인도)"},
    {"id": "ap-southeast-2", "name": "시드니 (호주)"},
    {"id": "us-west-2", "name": "오레곤 (미국)"},
    {"id": "eu-west-1", "name": "아일랜드 (유럽)"},
]


class ConfigManager:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        if base_dir is None:
            try:
                from android.storage import app_storage_path  # type: ignore
                base_dir = app_storage_path()
            except ImportError:
                base_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = base_dir
        self.config_path = os.path.join(base_dir, "config.json")
        self.history_path = os.path.join(base_dir, "rotation_history.json")
        self.config: dict = {}
        self.history: list = []

    def load_config(self) -> dict:
        if os.path.exists(self.config_path):
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            # deep copy
            self.config = json.loads(json.dumps(DEFAULT_CONFIG))
            self.save_config(self.config)
        return self.config

    def save_config(self, config: dict) -> None:
        self.config = config
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def get_aws_credentials(self) -> dict:
        aws = self.config.get("aws", {})
        return {
            "access_key_id": aws.get("access_key_id", ""),
            "secret_access_key": aws.get("secret_access_key", ""),
            "region": aws.get("region", "ap-southeast-1"),
        }

    def get_outline_config(self) -> dict:
        outline = self.config.get("outline", {})
        return {
            "api_url": outline.get("api_url", ""),
            "cert_sha256": outline.get("cert_sha256", ""),
        }

    def get_instance_name(self) -> str:
        return self.config.get("aws", {}).get("instance_name", "")

    def get_static_ip_prefix(self) -> str:
        return self.config.get("aws", {}).get("static_ip_prefix", "OutlineVPN-IP")

    def get_current_ip(self) -> str:
        return self.config.get("current_ip", "")

    def get_current_static_ip_name(self) -> str:
        return self.config.get("current_static_ip_name", "")

    def update_current_ip(self, ip: str, static_ip_name: str = "") -> None:
        """현재 IP/Static IP 이름을 갱신하고, Outline API URL의 호스트(IP) 부분도 동기화한다."""
        self.config["current_ip"] = ip
        self.config["current_static_ip_name"] = static_ip_name

        old_api_url = self.config.get("outline", {}).get("api_url", "")
        if old_api_url and ip:
            new_api_url = self._replace_host_in_api_url(old_api_url, ip)
            if new_api_url:
                self.config.setdefault("outline", {})["api_url"] = new_api_url

        self.save_config(self.config)

    @staticmethod
    def _replace_host_in_api_url(api_url: str, new_ip: str) -> str:
        """
        Outline Management API URL의 호스트(IP) 부분만 new_ip로 교체한다.
        예: 'https://abc123@52.77.49.10:65191/' -> 'https://abc123@18.143.37.150:65191/'
        다양한 입력 형식(스킴 유무, '@' 유무 등)을 안전하게 처리한다.
        """
        from urllib.parse import urlparse

        if not api_url:
            return ""
        try:
            parsed = urlparse(api_url if "://" in api_url else "https://" + api_url)
            scheme = parsed.scheme or "https"
            # userinfo 추출
            userinfo = ""
            netloc = parsed.netloc
            if "@" in netloc:
                userinfo, _ = netloc.rsplit("@", 1)
            # 포트
            port = parsed.port
            port_str = f":{port}" if port else ""
            # 새 netloc
            if userinfo:
                new_netloc = f"{userinfo}@{new_ip}{port_str}"
            else:
                new_netloc = f"{new_ip}{port_str}"
            path = parsed.path or ""
            query = f"?{parsed.query}" if parsed.query else ""
            fragment = f"#{parsed.fragment}" if parsed.fragment else ""
            return f"{scheme}://{new_netloc}{path}{query}{fragment}"
        except Exception:
            return ""

    def is_configured(self) -> bool:
        aws = self.config.get("aws", {})
        return bool(
            aws.get("access_key_id")
            and aws.get("secret_access_key")
            and aws.get("instance_name")
        )

    def is_outline_configured(self) -> bool:
        outline = self.config.get("outline", {})
        return bool(outline.get("api_url"))

    def load_history(self) -> list:
        if os.path.exists(self.history_path):
            with open(self.history_path, "r", encoding="utf-8") as f:
                self.history = json.load(f)
        else:
            self.history = []
        return self.history

    def add_history_entry(
        self,
        old_ip: str,
        new_ip: str,
        static_ip_name: str,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        self.load_history()
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "old_ip": old_ip,
            "new_ip": new_ip,
            "static_ip_name": static_ip_name,
            "region": self.config.get("aws", {}).get("region", ""),
            "success": success,
            "error": error,
        }
        self.history.insert(0, entry)
        # 최근 100건만 유지
        self.history = self.history[:100]
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(self.history, f, indent=2, ensure_ascii=False)

    def clear_history(self) -> None:
        self.history = []
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2, ensure_ascii=False)
