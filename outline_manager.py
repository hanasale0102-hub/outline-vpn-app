"""
Outline VPN Server Management API 클라이언트.
서버 정보 조회, 액세스 키 목록, hostname 업데이트, ss URL 파싱/생성 기능을 제공한다.
"""
import base64
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests
import urllib3

# Outline Manager API는 자체 서명 인증서를 사용 -> 경고만 끈다
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class AccessKey:
    id: str
    name: str
    access_url: str
    port: int = 0
    method: str = ""
    password: str = ""
    data_limit: Optional[int] = None


@dataclass
class ServerInfo:
    name: str
    server_id: str
    version: str
    hostname_for_access_keys: str
    port_for_new_access_keys: int
    metrics_enabled: bool
    created_timestamp_ms: Optional[int] = None


class OutlineAPIError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"Outline API 오류 ({status_code}): {message}")


class OutlineManager:
    def __init__(self, api_url: str = "", cert_sha256: str = "") -> None:
        # api_url은 'https://...' 형태. 끝 슬래시 제거.
        self.api_url = (api_url or "").rstrip("/")
        self.cert_sha256 = cert_sha256
        self.session = requests.Session()
        self.session.verify = False

    def _request(self, method: str, path: str, json_data: Optional[dict] = None) -> requests.Response:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            resp = self.session.request(
                method=method,
                url=url,
                json=json_data,
                timeout=30,
            )
            if resp.status_code >= 400:
                raise OutlineAPIError(resp.status_code, resp.text)
            return resp
        except requests.ConnectionError as e:
            raise OutlineAPIError(0, f"서버 연결 실패: {e}")
        except requests.Timeout:
            raise OutlineAPIError(0, "요청 시간 초과 (30초)")

    def get_server_info(self) -> ServerInfo:
        resp = self._request("GET", "server")
        data = resp.json()
        return ServerInfo(
            name=data.get("name", ""),
            server_id=data.get("serverId", ""),
            version=data.get("version", ""),
            hostname_for_access_keys=data.get("hostnameForAccessKeys", ""),
            port_for_new_access_keys=data.get("portForNewAccessKeys", 0),
            metrics_enabled=data.get("metricsEnabled", False),
            created_timestamp_ms=data.get("createdTimestampMs"),
        )

    def get_access_keys(self) -> list:
        resp = self._request("GET", "access-keys")
        data = resp.json()
        keys = []
        for k in data.get("accessKeys", []):
            keys.append(AccessKey(
                id=k.get("id", ""),
                name=k.get("name", "") or f"Key {k.get('id', '')}",
                access_url=k.get("accessUrl", ""),
                port=k.get("port", 0),
                method=k.get("method", ""),
                password=k.get("password", ""),
                data_limit=(k.get("dataLimit") or {}).get("bytes"),
            ))
        return keys

    def update_hostname(self, new_hostname: str) -> bool:
        resp = self._request(
            "PUT",
            "server/hostname-for-access-keys",
            json_data={"hostname": new_hostname},
        )
        return resp.status_code in (200, 204)

    def update_api_url(self, new_ip: str) -> None:
        """현재 self.api_url의 호스트 부분만 new_ip로 교체한다."""
        if not self.api_url:
            return
        parsed = urlparse(self.api_url if "://" in self.api_url else "https://" + self.api_url)
        port = parsed.port
        path = parsed.path or ""
        port_str = f":{port}" if port else ""
        scheme = parsed.scheme or "https"
        # userinfo 유지
        userinfo = ""
        if "@" in parsed.netloc:
            userinfo, _ = parsed.netloc.rsplit("@", 1)
            userinfo += "@"
        query = f"?{parsed.query}" if parsed.query else ""
        self.api_url = f"{scheme}://{userinfo}{new_ip}{port_str}{path}{query}".rstrip("/")

    def get_access_urls(self) -> list:
        keys = self.get_access_keys()
        return [k.access_url for k in keys]

    def test_connection(self) -> bool:
        try:
            self.get_server_info()
            return True
        except Exception:
            return False

    @staticmethod
    def parse_ss_url(ss_url: str) -> dict:
        """
        Shadowsocks URL을 파싱한다.
        예: 'ss://<base64(method:password)>@host:port/?outline=1#name'
            또는 'ss://<base64(method:password@host:port)>/?outline=1#name'
        반환: {'method', 'password', 'host', 'port'}
        """
        try:
            url = ss_url.replace("ss://", "", 1)
            # tag 제거
            url = url.split("#", 1)[0]
            url = url.split("?", 1)[0]

            if "@" in url:
                userinfo, hostinfo = url.rsplit("@", 1)
                # padding 보정
                userinfo += "=" * (-len(userinfo) % 4)
                decoded = base64.urlsafe_b64decode(userinfo).decode("utf-8").rstrip("/")
                method, password = decoded.split(":", 1)
                hostinfo = hostinfo.rstrip("/")
                host, port_str = hostinfo.rsplit(":", 1)
            else:
                # 전체 base64 디코드
                remainder = url.rstrip("/")
                remainder += "=" * (-len(remainder) % 4)
                decoded = base64.urlsafe_b64decode(remainder).decode("utf-8").rstrip("/")
                userinfo, hostinfo = decoded.rsplit("@", 1)
                method, password = userinfo.split(":", 1)
                host, port_str = hostinfo.rsplit(":", 1)

            port = int(port_str)
            return {
                "method": method,
                "password": password,
                "host": host,
                "port": port,
            }
        except Exception:
            return {
                "method": "",
                "password": "",
                "host": "",
                "port": 0,
            }

    @staticmethod
    def build_ss_url(method: str, password: str, host: str, port: int) -> str:
        userinfo = f"{method}:{password}".encode("utf-8")
        userinfo = base64.urlsafe_b64encode(userinfo).decode("utf-8").rstrip("=")
        return f"ss://{userinfo}@{host}:{port}/?outline=1"
