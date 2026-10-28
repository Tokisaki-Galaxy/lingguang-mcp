"""版本检查逻辑测试。

版本比较写错会给出错误的升级提示，这类问题在命令行里不明显，
所以单独测。
"""

from __future__ import annotations

from lingguang.core import update


class TestVersionCompare:
    def test_simple_newer(self) -> None:
        assert update.is_newer("0.4.0", "0.3.0")

    def test_simple_same(self) -> None:
        assert not update.is_newer("0.3.0", "0.3.0")

    def test_older(self) -> None:
        assert not update.is_newer("0.2.0", "0.3.0")

    def test_two_digit_minor_is_not_smaller(self) -> None:
        """字符串比较会认为 0.10.0 < 0.9.0，这是经典坑。"""
        assert update.is_newer("0.10.0", "0.9.0")

    def test_patch_compare(self) -> None:
        assert update.is_newer("1.2.10", "1.2.9")

    def test_parse_strips_local_suffix(self) -> None:
        assert update.parse_version("0.2.1.dev2+g2fc706b") == (0, 2, 1)


class TestDevVersion:
    def test_dev_suffix(self) -> None:
        assert update.is_dev_version("0.2.1.dev2+g2fc706b")

    def test_local_hash(self) -> None:
        assert update.is_dev_version("0.2.0+abc123")

    def test_unknown(self) -> None:
        assert update.is_dev_version("0.0.0+unknown")

    def test_release_is_not_dev(self) -> None:
        assert not update.is_dev_version("0.3.0")


class TestReportUrl:
    def test_compare_link_for_normal_versions(self) -> None:
        info = update.UpdateInfo("0.3.0", "0.4.0", None, False)
        url = info.report_url
        assert url is not None
        assert "compare/v0.3.0...v0.4.0" in url

    def test_falls_back_to_tags_for_odd_version(self) -> None:
        info = update.UpdateInfo("0.3.0", "0.4.0-beta", None, False)
        url = info.report_url
        assert url is not None
        assert url.endswith("/tags")

    def test_no_url_without_latest(self) -> None:
        info = update.UpdateInfo("0.3.0", None, "网络错误", False)
        assert info.report_url is None


class TestUpdateInfo:
    def test_dev_never_shows_update(self) -> None:
        info = update.UpdateInfo("0.2.1.dev2", "9.9.9", None, True)
        assert not info.has_update

    def test_error_never_shows_update(self) -> None:
        info = update.UpdateInfo("0.3.0", None, "timeout", False)
        assert not info.has_update

    def test_normal_update_detected(self) -> None:
        info = update.UpdateInfo("0.3.0", "0.4.0", None, False)
        assert info.has_update


class TestInstallMethod:
    def test_returns_command_string(self) -> None:
        cmd = update.install_method()
        assert isinstance(cmd, str)
        assert "lingguang" in cmd
