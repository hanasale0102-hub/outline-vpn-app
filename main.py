"""
Outline VPN IP Rotator — Kivy/Android 앱.

원본 APK 기능에 더해 두 가지 새 기능을 포함:
1) IP 교체 실행이 성공하면 '설정' 탭의 Outline API URL의 IP 부분을 새 IP로 자동 교체하고
   해당 변경을 config에 저장한 뒤 화면 입력 위젯에도 즉시 반영한다.
2) '설정' 탭에 새 API URL을 한 번에 클립보드로 복사할 수 있는 [복사] 버튼을 추가한다.
"""
import os
os.environ["KIVY_LOG_LEVEL"] = "warning"

import threading
import time

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.progressbar import ProgressBar
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp, sp
from kivy.utils import get_color_from_hex
from kivy.core.text import LabelBase

# 한글 폰트 등록 (APK assets에 포함된 NotoSansKR.ttf)
_font_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NotoSansKR.ttf")
if os.path.exists(_font_path):
    LabelBase.register(name="NotoSansKR", fn_regular=_font_path)
    LabelBase.register(name="Roboto", fn_regular=_font_path)

from config_manager import ConfigManager, AVAILABLE_REGIONS
from aws_manager import AWSManager
from outline_manager import OutlineManager


# 컬러 팔레트
BG_DARK = get_color_from_hex("#1a1a2e")
BG_CARD = get_color_from_hex("#16213e")
BG_INPUT = get_color_from_hex("#0f3460")
COLOR_PRIMARY = get_color_from_hex("#4FC3F7")
COLOR_SUCCESS = get_color_from_hex("#4CAF50")
COLOR_DANGER = get_color_from_hex("#E53935")
COLOR_WARNING = get_color_from_hex("#FFC107")
COLOR_TEXT = get_color_from_hex("#FFFFFF")
COLOR_TEXT_DIM = get_color_from_hex("#888888")


def _replace_ip_in_url(url: str, new_ip: str) -> str:
    """
    URL에서 '@<host>:<port>' 패턴의 호스트 부분만 new_ip로 교체한다.
    https://, ss:// 등 모든 스킴 + '@' 가 있는 형식에서 동작.
    실패 시 원본 그대로 반환.

    예:
      'ss://abc@54.254.69.72:65191/?outline=1' + '47.131.44.210'
        → 'ss://abc@47.131.44.210:65191/?outline=1'
      'https://xxx@54.254.69.72:65191/' + '47.131.44.210'
        → 'https://xxx@47.131.44.210:65191/'
    """
    import re
    if not url or not new_ip:
        return url
    try:
        # @<host>:  → @<new_ip>:  로 교체 (호스트는 :/@ 미포함 문자열)
        pattern = r'@([^:/@\s?#]+):'
        new_url, n = re.subn(pattern, f'@{new_ip}:', url, count=1)
        if n > 0:
            return new_url
        # '@'가 없는 URL의 경우 (예: 'https://1.2.3.4:5/path')
        pattern2 = r'(://)([^:/@\s?#]+)(:|/|$)'
        new_url, n = re.subn(pattern2, lambda m: f"{m.group(1)}{new_ip}{m.group(3)}", url, count=1)
        return new_url if n > 0 else url
    except Exception:
        return url


# 기존 이름 유지 (이전 코드 호환)
_replace_ip_in_outline_url = _replace_ip_in_url


class OutlineVPNApp(App):

    def build(self):
        self.title = "Outline VPN IP Rotator"
        self.config_mgr = ConfigManager()
        self.config_mgr.load_config()
        self.aws_mgr = None
        self.outline_mgr = None
        self.is_rotating = False
        self.current_keys = []

        root = TabbedPanel(
            do_default_tab=False,
            tab_width=dp(120),
        )
        root.background_color = BG_DARK

        tab1 = TabbedPanelItem(text="IP 교체")
        tab1.add_widget(self._build_rotation_tab())
        root.add_widget(tab1)

        tab2 = TabbedPanelItem(text="설정")
        tab2.add_widget(self._build_settings_tab())
        root.add_widget(tab2)

        tab3 = TabbedPanelItem(text="이력")
        tab3.add_widget(self._build_history_tab())
        root.add_widget(tab3)

        Clock.schedule_once(lambda dt: self._load_settings(), 0.5)
        return root

    # ----- Tab 1: IP 교체 -----
    def _build_rotation_tab(self):
        scroll = ScrollView()
        layout = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8), size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))

        layout.add_widget(self._make_section_label("서버 상태"))

        status_grid = GridLayout(cols=2, spacing=dp(5), size_hint_y=None, height=dp(100))

        status_grid.add_widget(Label(text="인스턴스:", font_size=sp(14), halign="right", size_hint_x=0.4))
        self.lbl_instance = Label(text="-", font_size=sp(14), color=COLOR_PRIMARY, halign="left", size_hint_x=0.6)
        status_grid.add_widget(self.lbl_instance)

        status_grid.add_widget(Label(text="현재 IP:", font_size=sp(14), halign="right", size_hint_x=0.4))
        self.lbl_ip = Label(text="-", font_size=sp(14), color=COLOR_PRIMARY, halign="left", size_hint_x=0.6)
        status_grid.add_widget(self.lbl_ip)

        status_grid.add_widget(Label(text="리전:", font_size=sp(14), halign="right", size_hint_x=0.4))
        self.lbl_region = Label(text="-", font_size=sp(14), color=COLOR_TEXT_DIM, halign="left", size_hint_x=0.6)
        status_grid.add_widget(self.lbl_region)

        status_grid.add_widget(Label(text="상태:", font_size=sp(14), halign="right", size_hint_x=0.4))
        self.lbl_state = Label(text="-", font_size=sp(14), color=COLOR_TEXT_DIM, halign="left", size_hint_x=0.6)
        status_grid.add_widget(self.lbl_state)
        layout.add_widget(status_grid)

        btn_refresh = Button(
            text="상태 새로고침",
            size_hint_y=None,
            height=dp(45),
            font_size=sp(15),
            background_color=BG_INPUT,
        )
        btn_refresh.bind(on_press=self._on_refresh_status)
        layout.add_widget(btn_refresh)

        layout.add_widget(self._make_section_label("IP 교체"))

        self.progress_bar = ProgressBar(max=100, value=0, size_hint_y=None, height=dp(20))
        layout.add_widget(self.progress_bar)

        self.lbl_progress = Label(
            text="대기 중",
            font_size=sp(13),
            color=COLOR_TEXT_DIM,
            size_hint_y=None,
            height=dp(25),
        )
        layout.add_widget(self.lbl_progress)

        self.btn_rotate = Button(
            text="IP 교체 실행",
            size_hint_y=None,
            height=dp(55),
            font_size=sp(18),
            background_color=COLOR_DANGER,
            bold=True,
        )
        self.btn_rotate.bind(on_press=self._on_rotate)
        layout.add_widget(self.btn_rotate)

        layout.add_widget(self._make_section_label("액세스 키"))

        self.keys_layout = BoxLayout(orientation="vertical", spacing=dp(5), size_hint_y=None)
        self.keys_layout.bind(minimum_height=self.keys_layout.setter("height"))
        self.lbl_no_keys = Label(
            text="IP 교체 후 키가 표시됩니다.",
            font_size=sp(13),
            color=COLOR_TEXT_DIM,
            size_hint_y=None,
            height=dp(40),
        )
        self.keys_layout.add_widget(self.lbl_no_keys)
        layout.add_widget(self.keys_layout)

        self.btn_copy_all = Button(
            text="전체 복사",
            size_hint_y=None,
            height=dp(40),
            font_size=sp(14),
            background_color=BG_INPUT,
            disabled=True,
        )
        self.btn_copy_all.bind(on_press=self._on_copy_all)
        layout.add_widget(self.btn_copy_all)

        scroll.add_widget(layout)
        return scroll

    # ----- Tab 2: 설정 -----
    def _build_settings_tab(self):
        scroll = ScrollView()
        layout = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8), size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))

        layout.add_widget(self._make_section_label("AWS 설정"))

        self.input_aws_key = self._make_input_row(layout, "Access Key ID")
        self.input_aws_secret = self._make_input_row(layout, "Secret Access Key", password=True)

        region_row = BoxLayout(size_hint_y=None, height=dp(45), spacing=dp(5))
        region_row.add_widget(Label(text="리전:", font_size=sp(13), size_hint_x=0.35, halign="right"))
        region_names = [r["name"] for r in AVAILABLE_REGIONS]
        self.spinner_region = Spinner(
            text=region_names[0],
            values=region_names,
            size_hint_x=0.65,
            font_size=sp(13),
        )
        region_row.add_widget(self.spinner_region)
        layout.add_widget(region_row)

        self.input_instance = self._make_input_row(layout, "인스턴스 이름")
        self.input_prefix = self._make_input_row(layout, "Static IP 접두사")

        btn_test_aws = Button(
            text="AWS 연결 테스트",
            size_hint_y=None,
            height=dp(42),
            font_size=sp(14),
            background_color=COLOR_PRIMARY,
        )
        btn_test_aws.bind(on_press=self._on_test_aws)
        layout.add_widget(btn_test_aws)

        self.lbl_aws_test = Label(
            text="",
            font_size=sp(13),
            size_hint_y=None,
            height=dp(25),
        )
        layout.add_widget(self.lbl_aws_test)

        layout.add_widget(self._make_section_label("Outline 설정"))

        hint_label = Label(
            text="Outline Manager > 서버 설정 > Management API에서 확인",
            font_size=sp(11),
            color=COLOR_TEXT_DIM,
            size_hint_y=None,
            height=dp(22),
        )
        layout.add_widget(hint_label)

        # API URL 입력 + 복사 버튼 (★ 신규)
        self.input_api_url = self._make_input_row(layout, "API URL")

        # 복사 버튼 한 줄
        copy_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(5))
        copy_row.add_widget(Label(text="", size_hint_x=0.35))
        self.btn_copy_api_url = Button(
            text="API URL 복사",
            size_hint_x=0.65,
            font_size=sp(14),
            background_color=COLOR_PRIMARY,
        )
        self.btn_copy_api_url.bind(on_press=self._on_copy_api_url)
        copy_row.add_widget(self.btn_copy_api_url)
        layout.add_widget(copy_row)

        self.input_cert = self._make_input_row(layout, "Cert SHA256 (선택)")

        btn_test_outline = Button(
            text="Outline 연결 테스트",
            size_hint_y=None,
            height=dp(42),
            font_size=sp(14),
            background_color=COLOR_PRIMARY,
        )
        btn_test_outline.bind(on_press=self._on_test_outline)
        layout.add_widget(btn_test_outline)

        self.lbl_outline_test = Label(
            text="",
            font_size=sp(13),
            size_hint_y=None,
            height=dp(25),
        )
        layout.add_widget(self.lbl_outline_test)

        layout.add_widget(Label(text="", size_hint_y=None, height=dp(15)))

        btn_save = Button(
            text="설정 저장",
            size_hint_y=None,
            height=dp(50),
            font_size=sp(16),
            background_color=COLOR_SUCCESS,
            bold=True,
        )
        btn_save.bind(on_press=self._on_save_settings)
        layout.add_widget(btn_save)

        self.lbl_save_result = Label(
            text="",
            font_size=sp(13),
            size_hint_y=None,
            height=dp(25),
        )
        layout.add_widget(self.lbl_save_result)

        scroll.add_widget(layout)
        return scroll

    # ----- Tab 3: 이력 -----
    def _build_history_tab(self):
        layout = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))

        btn_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))

        btn_refresh = Button(
            text="새로고침",
            font_size=sp(14),
            background_color=COLOR_PRIMARY,
        )
        btn_refresh.bind(on_press=self._on_refresh_history)
        btn_row.add_widget(btn_refresh)

        btn_clear = Button(
            text="이력 초기화",
            font_size=sp(14),
            background_color=get_color_from_hex("#757575"),
        )
        btn_clear.bind(on_press=self._on_clear_history)
        btn_row.add_widget(btn_clear)

        layout.add_widget(btn_row)

        scroll = ScrollView()
        self.history_layout = BoxLayout(orientation="vertical", spacing=dp(3), size_hint_y=None)
        self.history_layout.bind(minimum_height=self.history_layout.setter("height"))
        scroll.add_widget(self.history_layout)
        layout.add_widget(scroll)
        return layout

    # ----- 설정 로드/저장 -----
    def _load_settings(self):
        cfg = self.config_mgr.config
        aws = cfg.get("aws", {})
        self.input_aws_key.text = aws.get("access_key_id", "")
        self.input_aws_secret.text = aws.get("secret_access_key", "")
        self.input_instance.text = aws.get("instance_name", "")
        self.input_prefix.text = aws.get("static_ip_prefix", "OutlineVPN-IP")

        region_id = aws.get("region", "ap-southeast-1")
        for r in AVAILABLE_REGIONS:
            if r["id"] == region_id:
                self.spinner_region.text = r["name"]
                break

        outline = cfg.get("outline", {})
        self.input_api_url.text = outline.get("api_url", "")
        self.input_cert.text = outline.get("cert_sha256", "")

        # 현재 IP 표시
        self.lbl_ip.text = cfg.get("current_ip", "") or "-"
        self.lbl_instance.text = aws.get("instance_name", "") or "-"
        for r in AVAILABLE_REGIONS:
            if r["id"] == region_id:
                self.lbl_region.text = r["name"]
                break

        self._refresh_history_display()

    def _on_save_settings(self, instance=None):
        # 리전 spinner -> region id
        region_id = "ap-southeast-1"
        for r in AVAILABLE_REGIONS:
            if r["name"] == self.spinner_region.text:
                region_id = r["id"]
                break

        self.config_mgr.config["aws"] = {
            "access_key_id": self.input_aws_key.text.strip(),
            "secret_access_key": self.input_aws_secret.text.strip(),
            "region": region_id,
            "instance_name": self.input_instance.text.strip(),
            "static_ip_prefix": self.input_prefix.text.strip() or "OutlineVPN-IP",
        }
        self.config_mgr.config["outline"] = {
            "api_url": self.input_api_url.text.strip(),
            "cert_sha256": self.input_cert.text.strip(),
        }
        self.config_mgr.save_config(self.config_mgr.config)
        self._init_managers()

        self.lbl_save_result.text = "설정이 저장되었습니다."
        self.lbl_save_result.color = COLOR_SUCCESS
        Clock.schedule_once(lambda dt: setattr(self.lbl_save_result, "text", ""), 3)

    # ----- Manager 초기화 -----
    def _init_managers(self):
        aws = self.config_mgr.get_aws_credentials()
        key_id = aws.get("access_key_id")
        secret = aws.get("secret_access_key")
        region = aws.get("region")
        if key_id and secret:
            self.aws_mgr = AWSManager(key_id, secret, region)
        outline = self.config_mgr.get_outline_config()
        api_url = outline.get("api_url")
        cert = outline.get("cert_sha256")
        if api_url:
            self.outline_mgr = OutlineManager(api_url, cert)

    # ----- AWS 테스트 -----
    def _on_test_aws(self, instance=None):
        self._on_save_settings()
        if not self.aws_mgr:
            self.lbl_aws_test.text = "AWS 자격증명을 입력하세요."
            self.lbl_aws_test.color = COLOR_DANGER
            return
        self.lbl_aws_test.text = "테스트 중..."
        self.lbl_aws_test.color = COLOR_WARNING

        def worker():
            ok = self.aws_mgr.test_connection()
            Clock.schedule_once(lambda dt: self._show_aws_test_result(ok))

        threading.Thread(target=worker, daemon=True).start()

    def _show_aws_test_result(self, ok):
        if ok:
            self.lbl_aws_test.text = "연결 성공!"
            self.lbl_aws_test.color = COLOR_SUCCESS
        else:
            self.lbl_aws_test.text = "연결 실패. 자격증명을 확인하세요."
            self.lbl_aws_test.color = COLOR_DANGER

    # ----- Outline 테스트 -----
    def _on_test_outline(self, instance=None):
        self._on_save_settings()
        if not self.outline_mgr:
            self.lbl_outline_test.text = "API URL을 입력하세요."
            self.lbl_outline_test.color = COLOR_DANGER
            return
        self.lbl_outline_test.text = "테스트 중..."
        self.lbl_outline_test.color = COLOR_WARNING

        def worker():
            ok = False
            msg = "연결 실패. API URL을 확인하세요."
            try:
                info = self.outline_mgr.get_server_info()
                ok = True
                msg = f"연결 성공! (v{info.version})"
            except Exception:
                ok = False
                msg = "연결 실패. API URL을 확인하세요."
            Clock.schedule_once(lambda dt: self._show_outline_test_result(ok, msg))

        threading.Thread(target=worker, daemon=True).start()

    def _show_outline_test_result(self, ok, msg):
        self.lbl_outline_test.text = msg
        self.lbl_outline_test.color = COLOR_SUCCESS if ok else COLOR_DANGER

    # ----- 상태 새로고침 -----
    def _on_refresh_status(self, instance=None):
        self._init_managers()
        if not self.aws_mgr:
            self._show_popup("경고", "AWS 설정을 먼저 입력하고 저장하세요.")
            return
        inst_name = self.config_mgr.get_instance_name()
        if not inst_name:
            self._show_popup("경고", "인스턴스 이름을 설정에서 입력하세요.")
            return

        def worker():
            try:
                info = self.aws_mgr.get_instance_info(inst_name)
                static = self.aws_mgr.get_current_static_ip(inst_name)
                ip = (static or {}).get("ip_address") or info.get("public_ip", "-")
                state = info.get("state", "-")
                region_id = info.get("region", "")
                region_name = region_id
                for r in AVAILABLE_REGIONS:
                    if r["id"] == region_id:
                        region_name = r["name"]
                        break
                Clock.schedule_once(lambda dt: self._update_status(inst_name, ip, region_name, state))
            except Exception as e:
                Clock.schedule_once(lambda dt: self._show_popup("오류", f"상태 조회 실패:\n{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _update_status(self, instance, ip, region, state):
        self.lbl_instance.text = instance
        self.lbl_ip.text = ip
        self.lbl_region.text = region
        self.lbl_state.text = state
        if state == "running":
            self.lbl_state.color = COLOR_SUCCESS
        elif state == "stopped":
            self.lbl_state.color = COLOR_DANGER
        else:
            self.lbl_state.color = COLOR_WARNING

    # ----- IP 교체 -----
    def _on_rotate(self, instance=None):
        if self.is_rotating:
            return
        self._on_save_settings()
        if not self.aws_mgr:
            self._show_popup("경고", "AWS 설정을 먼저 입력하고 저장하세요.")
            return
        inst_name = self.config_mgr.get_instance_name()
        if not inst_name:
            self._show_popup("경고", "인스턴스 이름을 설정에서 입력하세요.")
            return

        self._show_confirm_popup(
            "IP 교체 확인",
            "VPN IP를 교체합니다.\n기존 IP로 접속 중인 사용자의 연결이 끊깁니다.\n\n계속하시겠습니까?",
            lambda: self._start_rotation(inst_name),
        )

    def _start_rotation(self, inst_name):
        self.is_rotating = True
        self.btn_rotate.disabled = True
        self.btn_rotate.text = "교체 진행 중..."
        self.progress_bar.value = 0
        self.lbl_progress.text = "시작 중..."
        self.lbl_progress.color = COLOR_WARNING

        def worker():
            access_keys = []
            result = None
            try:
                current_ip_name = self.config_mgr.get_current_static_ip_name()
                prefix = self.config_mgr.get_static_ip_prefix()

                result = self.aws_mgr.rotate_ip(
                    instance_name=inst_name,
                    current_static_ip_name=current_ip_name,
                    ip_name_prefix=prefix,
                    progress_callback=lambda msg, pct: Clock.schedule_once(
                        lambda dt, m=msg, p=pct: self._update_progress(m, p)
                    ),
                )

                if not result.success:
                    Clock.schedule_once(lambda dt: self._rotation_failed(result.error))
                    return

                # Outline 서버가 살아날 때까지 잠시 대기
                Clock.schedule_once(lambda dt: self._update_progress("서버 준비 대기 중 (10초)...", 91))
                time.sleep(10)

                # Outline manager 가 있으면 hostname/api url 갱신 시도
                if self.outline_mgr:
                    # 1) Outline hostname 업데이트 (재시도 포함)
                    fixed = False
                    for attempt in range(3):
                        Clock.schedule_once(
                            lambda dt, a=attempt + 1: self._update_progress(
                                f"Outline hostname 업데이트 중... ({a}/3)", 93
                            )
                        )
                        try:
                            self.outline_mgr.update_hostname(result.new_ip)
                            fixed = True
                            break
                        except Exception:
                            time.sleep(2)

                    # 2) outline_mgr 자체의 api_url 도 새 IP 로 갱신해서 후속 호출이 동작하게 함
                    try:
                        self.outline_mgr.update_api_url(result.new_ip)
                    except Exception:
                        pass

                    # 3) 액세스 키 재조회
                    try:
                        time.sleep(5)
                        access_keys = self.outline_mgr.get_access_keys()
                    except Exception:
                        access_keys = []

                # config의 current_ip 및 outline.api_url 갱신
                self.config_mgr.update_current_ip(result.new_ip, result.new_static_ip_name)

                # 이력 기록
                self.config_mgr.add_history_entry(
                    old_ip=result.old_ip,
                    new_ip=result.new_ip,
                    static_ip_name=result.new_static_ip_name,
                    success=True,
                )

                Clock.schedule_once(lambda dt: self._rotation_complete(result, access_keys))
            except Exception as e:
                try:
                    self.config_mgr.add_history_entry(
                        old_ip="",
                        new_ip="",
                        static_ip_name="",
                        success=False,
                        error=str(e),
                    )
                except Exception:
                    pass
                Clock.schedule_once(lambda dt: self._rotation_failed(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _update_progress(self, msg, pct):
        self.progress_bar.value = pct
        self.lbl_progress.text = msg
        self.lbl_progress.color = COLOR_WARNING

    def _rotation_complete(self, result, access_keys):
        self.is_rotating = False
        self.btn_rotate.disabled = False
        self.btn_rotate.text = "IP 교체 실행"
        self.progress_bar.value = 100
        self.lbl_progress.text = f"교체 완료! {result.old_ip} → {result.new_ip}"
        self.lbl_progress.color = COLOR_SUCCESS
        self.lbl_ip.text = result.new_ip

        # ★ 신규 기능 1: Outline API URL 의 IP 부분을 자동 교체하여 입력 위젯에도 반영
        try:
            old_url = self.input_api_url.text if self.input_api_url else ""
            if not old_url:
                # 입력 위젯이 비었다면 config에서 다시 가져옴 (update_current_ip 가 이미 갱신했음)
                old_url = self.config_mgr.get_outline_config().get("api_url", "")
            new_url = _replace_ip_in_url(old_url, result.new_ip)
            if new_url:
                self.input_api_url.text = new_url
                # config 도 한 번 더 정합성 맞춤
                self.config_mgr.config.setdefault("outline", {})["api_url"] = new_url
                self.config_mgr.save_config(self.config_mgr.config)
                # 사용자가 바로 복사할 수 있다는 안내
                self.lbl_save_result.text = "Outline API URL이 새 IP로 갱신되었습니다. 설정 탭에서 [API URL 복사]를 누르세요."
                self.lbl_save_result.color = COLOR_SUCCESS
                Clock.schedule_once(lambda dt: setattr(self.lbl_save_result, "text", ""), 6)
        except Exception:
            pass

        # ★ 신규 기능 2: 액세스 키의 ss:// URL 중 @~: 사이 IP 도 새 IP 로 강제 교체
        # (Outline 서버 hostname 캐시가 옛 IP일 가능성 대비 — 클라이언트에서 안전하게 보정)
        try:
            if result.new_ip and access_keys:
                for key in access_keys:
                    if getattr(key, 'access_url', None):
                        key.access_url = _replace_ip_in_url(key.access_url, result.new_ip)
        except Exception:
            pass

        self._display_keys(access_keys)
        self._refresh_history_display()

    def _rotation_failed(self, error):
        self.is_rotating = False
        self.btn_rotate.disabled = False
        self.btn_rotate.text = "IP 교체 실행"
        self.lbl_progress.text = "교체 실패!"
        self.lbl_progress.color = COLOR_DANGER
        self._show_popup("IP 교체 실패", str(error))

    # ----- 액세스 키 표시 -----
    def _display_keys(self, access_keys):
        self.keys_layout.clear_widgets()
        self.current_keys = access_keys or []
        if not access_keys:
            self.keys_layout.add_widget(Label(
                text="키 정보를 가져올 수 없습니다.",
                font_size=sp(13),
                color=COLOR_TEXT_DIM,
                size_hint_y=None,
                height=dp(40),
            ))
            self.btn_copy_all.disabled = True
            return

        self.btn_copy_all.disabled = False
        for key in access_keys:
            key_box = BoxLayout(
                orientation="vertical",
                spacing=dp(3),
                size_hint_y=None,
                height=dp(80),
                padding=dp(5),
            )
            name_label = Label(
                text=f"{key.name}:",
                font_size=sp(13),
                bold=True,
                halign="left",
                size_hint_y=None,
                height=dp(22),
            )
            name_label.bind(size=name_label.setter("text_size"))
            key_box.add_widget(name_label)

            url_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(5))
            url_input = TextInput(
                text=key.access_url,
                font_size=sp(11),
                readonly=True,
                multiline=False,
                size_hint_x=0.75,
            )
            url_row.add_widget(url_input)
            btn_copy = Button(
                text="복사",
                font_size=sp(13),
                size_hint_x=0.25,
                background_color=COLOR_PRIMARY,
            )
            btn_copy.bind(on_press=lambda inst, url=key.access_url: self._copy_text(url))
            url_row.add_widget(btn_copy)
            key_box.add_widget(url_row)

            self.keys_layout.add_widget(key_box)

    def _copy_text(self, text):
        """Kivy Clipboard → 실패 시 Android Native Clipboard fallback."""
        try:
            Clipboard.copy(text)
            self._show_popup("복사 완료", "클립보드에 복사되었습니다.")
            return
        except Exception:
            pass
        try:
            from jnius import autoclass  # type: ignore
            Context = autoclass("android.content.Context")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE)
            ClipData = autoclass("android.content.ClipData")
            clip = ClipData.newPlainText("ss_url", text)
            clipboard.setPrimaryClip(clip)
            self._show_popup("복사 완료", "클립보드에 복사되었습니다.")
        except Exception:
            self._show_popup("알림", f"수동으로 복사하세요:\n{text}")

    def _on_copy_all(self, instance=None):
        all_text = "\n".join(f"{k.name}: {k.access_url}" for k in self.current_keys)
        self._copy_text(all_text)

    def _on_copy_api_url(self, instance=None):
        """★ 신규: 설정 탭의 Outline API URL 을 클립보드로 복사한다."""
        text = (self.input_api_url.text or "").strip()
        if not text:
            self._show_popup("알림", "API URL이 비어 있습니다.")
            return
        self._copy_text(text)

    # ----- 이력 -----
    def _on_refresh_history(self, instance=None):
        self._refresh_history_display()

    def _refresh_history_display(self):
        self.history_layout.clear_widgets()
        history = self.config_mgr.load_history()
        if not history:
            self.history_layout.add_widget(Label(
                text="교체 이력이 없습니다.",
                font_size=sp(13),
                color=COLOR_TEXT_DIM,
                size_hint_y=None,
                height=dp(40),
            ))
            return
        for entry in history:
            row = BoxLayout(size_hint_y=None, height=dp(55), spacing=dp(3), padding=dp(3))
            info_box = BoxLayout(orientation="vertical", size_hint_x=0.8)
            ts = entry.get("timestamp", "")
            old_ip = entry.get("old_ip", "-")
            new_ip = entry.get("new_ip", "-")
            success = entry.get("success", False)
            info_box.add_widget(Label(
                text=ts,
                font_size=sp(11),
                halign="left",
                size_hint_y=None,
                height=dp(18),
            ))
            info_box.add_widget(Label(
                text=f"{old_ip} → {new_ip}",
                font_size=sp(12),
                halign="left",
                color=COLOR_PRIMARY,
                size_hint_y=None,
                height=dp(20),
            ))
            row.add_widget(info_box)

            result_text = "성공" if success else "실패"
            result_color = COLOR_SUCCESS if success else COLOR_DANGER
            row.add_widget(Label(
                text=result_text,
                font_size=sp(12),
                bold=True,
                color=result_color,
                size_hint_x=0.2,
            ))
            self.history_layout.add_widget(row)

    def _on_clear_history(self, instance=None):
        self._show_confirm_popup(
            "이력 초기화",
            "모든 교체 이력을 삭제하시겠습니까?",
            lambda: self._do_clear_history(),
        )

    def _do_clear_history(self):
        self.config_mgr.clear_history()
        self._refresh_history_display()

    # ----- UI Helpers -----
    def _make_section_label(self, text):
        lbl = Label(
            text=text,
            font_size=sp(17),
            bold=True,
            halign="left",
            size_hint_y=None,
            height=dp(35),
            color=COLOR_TEXT,
        )
        lbl.bind(size=lbl.setter("text_size"))
        return lbl

    def _make_input_row(self, parent, label_text, password=False):
        row = BoxLayout(size_hint_y=None, height=dp(45), spacing=dp(5))
        row.add_widget(Label(
            text=f"{label_text}:",
            font_size=sp(13),
            size_hint_x=0.35,
            halign="right",
        ))
        inp = TextInput(
            font_size=sp(13),
            multiline=False,
            password=password,
            size_hint_x=0.65,
        )
        row.add_widget(inp)
        parent.add_widget(row)
        return inp

    def _show_popup(self, title, message):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        content.add_widget(Label(text=message, font_size=sp(14)))
        btn = Button(text="확인", size_hint_y=None, height=dp(42), font_size=sp(14))
        content.add_widget(btn)
        popup = Popup(title=title, content=content, size_hint=(0.85, 0.4))
        btn.bind(on_press=popup.dismiss)
        popup.open()

    def _show_confirm_popup(self, title, message, on_confirm):
        content = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        content.add_widget(Label(text=message, font_size=sp(14)))
        btn_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(10))
        btn_yes = Button(text="예", font_size=sp(14), background_color=COLOR_DANGER)
        btn_no = Button(text="아니오", font_size=sp(14))
        btn_row.add_widget(btn_yes)
        btn_row.add_widget(btn_no)
        content.add_widget(btn_row)
        popup = Popup(title=title, content=content, size_hint=(0.85, 0.45))

        def on_yes(inst):
            popup.dismiss()
            on_confirm()
        btn_yes.bind(on_press=on_yes)
        btn_no.bind(on_press=popup.dismiss)
        popup.open()


if __name__ == "__main__":
    OutlineVPNApp().run()
