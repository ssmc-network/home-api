"""yt-dlpを呼び出して動画のダウンロード・情報取得を行うモジュール。"""

from pathlib import Path

from yt_dlp import YoutubeDL  # type: ignore[import]


def download_youtube(url: str, output_dir: str) -> None:
    """URLの動画をmp4として output_dir へ保存する。"""
    path_out_dir = Path(output_dir)
    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(path_out_dir / "%(title).50s.mp4"),
        "merge_output_format": "mp4",
        "postprocessors": [],
    }
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])


def get_youtube_title(url: str) -> str:
    """URLの動画タイトルを取得する(ダウンロードは行わない)。"""
    with YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        # yt-dlpは型スタブを持たずextract_infoの戻り値がAnyになるため、
        # str()で明示的に確定させる(mypyのwarn_return_any対策も兼ねる)。
        return str(info.get("title", "unknown"))
