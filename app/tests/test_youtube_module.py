from unittest.mock import MagicMock, patch

from modules.youtube_module import download_youtube, get_youtube_title


def _patched_ydl() -> tuple[MagicMock, MagicMock]:
    """YoutubeDL をモックし、(クラスのモック, インスタンスのモック) を返す。"""
    ydl_cls = MagicMock()
    instance = MagicMock()
    ydl_cls.return_value.__enter__.return_value = instance
    return ydl_cls, instance


class TestDownloadYoutube:
    def test_passes_expected_options_to_ytdlp(self) -> None:
        ydl_cls, instance = _patched_ydl()

        with patch("modules.youtube_module.YoutubeDL", ydl_cls):
            download_youtube("https://example.test/v", "/data")

        opts = ydl_cls.call_args.args[0]
        assert opts["merge_output_format"] == "mp4"
        # ファイル名が長くなりすぎないようタイトルを50文字で切っている
        assert opts["outtmpl"] == "/data/%(title).50s.mp4"
        instance.download.assert_called_once_with(["https://example.test/v"])

    def test_output_dir_is_joined_as_path(self) -> None:
        ydl_cls, _ = _patched_ydl()

        with patch("modules.youtube_module.YoutubeDL", ydl_cls):
            download_youtube("https://example.test/v", "/mnt/videos/")

        assert ydl_cls.call_args.args[0]["outtmpl"] == "/mnt/videos/%(title).50s.mp4"


class TestGetYoutubeTitle:
    def test_returns_title_without_downloading(self) -> None:
        ydl_cls, instance = _patched_ydl()
        instance.extract_info.return_value = {"title": "サンプル動画"}

        with patch("modules.youtube_module.YoutubeDL", ydl_cls):
            assert get_youtube_title("https://example.test/v") == "サンプル動画"

        instance.extract_info.assert_called_once_with("https://example.test/v", download=False)

    def test_falls_back_to_unknown_when_title_is_missing(self) -> None:
        ydl_cls, instance = _patched_ydl()
        instance.extract_info.return_value = {}

        with patch("modules.youtube_module.YoutubeDL", ydl_cls):
            assert get_youtube_title("https://example.test/v") == "unknown"

    def test_non_string_title_is_coerced_to_str(self) -> None:
        ydl_cls, instance = _patched_ydl()
        instance.extract_info.return_value = {"title": 12345}

        with patch("modules.youtube_module.YoutubeDL", ydl_cls):
            title = get_youtube_title("https://example.test/v")

        assert title == "12345"
        assert isinstance(title, str)
