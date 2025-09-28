import re
import time
from typing import Any, Literal, Optional
from urllib.parse import urljoin

import neologdn
import requests
from bs4 import BeautifulSoup

BASE = "https://www.uta-net.com/"


def get_target_lyric_soup(
    target_id: str,
    target: Literal["artist", "lyricist", "composer", "arranger"] = "artist",
    mode: int = 4,
    page_no: int = 1,
    base: str = BASE,
) -> BeautifulSoup:
    """_summary_

    Args:
        target_id (str):
        target (str): ["artist", "lyricist", "composer", "arranger"] Defaults to "artist".
        base (str, optional): Defaults to "https://www.uta-net.com/".
        mode (int, optional): Defaults to 4.
            1 : 曲名昇順, 2 : 曲名降順
            3 : 人気が低い順, 4 : 人気が高い順
            5 : 古い順, 6 : 新しい順
        page_no (int, optional): Defaults to 1.

    Raises:
        ValueError: target と mode の入力値チェック

    Returns:
        BeautifulSoup: 一覧ページのsoup
    """

    lower_target = target.lower()
    if lower_target not in ["artist", "lyricist", "composer", "arranger"]:
        raise ValueError(
            'target は ["artist","lyricist","composer","arranger"] のみ受け付けます。'
            f"入力 : {target}"
        )
    if not (isinstance(mode, int) and 1 <= mode <= 6):
        raise ValueError(
            "target は 1 ~ 6 の整数型のみ受け付けます。"
            f"入力 : {mode} (type:{type(mode)})"
        )
    target_url = urljoin(base, f"{lower_target}/")
    target_url = urljoin(target_url, f"{str(target_id)}/")
    target_url = urljoin(target_url, f"{mode}/{page_no}/")
    response = requests.get(target_url)
    soup = BeautifulSoup(response.text, "html.parser")
    return soup


def parse_total_pages(soup: BeautifulSoup) -> int:
    # ① 一番確実：ページ情報のテキストから読む
    page_info = soup.select_one(
        "#songlist-sort-paging .col-7.col-lg-3.text-start.text-lg-end.d-none.d-lg-block"
    )
    if page_info:
        m = re.search(r"全(\d+)ページ中", page_info.get_text())
        if m:
            return int(m.group(1))
    # ② 代替：ページャーのリンク最後尾を読む（サイト側のマークアップ変化に弱い場合あり）
    pager_numbers = [
        int(a.get_text())
        for a in soup.select("#songlist-sort-paging a")
        if a.get_text().isdigit()
    ]
    if pager_numbers:
        return max(pager_numbers)
    # ③ どちらも無ければ1ページ扱い
    return 1


def get_song_list_from_soup(
    soup: BeautifulSoup, base: str = BASE
) -> list[dict[str, Optional[Any]]]:
    rows = soup.select("table.songlist-table tbody.songlist-table-body tr")
    out = []
    for tr in rows:
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        a_song = tds[0].select_one("a")
        title = (
            a_song.select_one(".songlist-title").get_text(strip=True)
            if a_song
            else None
        )
        lyrics_url = (
            urljoin(base, a_song.get("href")) if a_song and a_song.get("href") else None
        )
        artist = tds[1].get_text(strip=True) if len(tds) > 1 else None
        lyricist = tds[2].get_text(strip=True) if len(tds) > 2 else None
        composer = tds[3].get_text(strip=True) if len(tds) > 3 else None
        arranger = tds[4].get_text(strip=True) if len(tds) > 4 else None

        out.append(
            {
                "title": title,
                "artist": artist,
                "lyricist": lyricist,
                "composer": composer,
                "arranger": arranger,
                "lyrics_url": lyrics_url,
            }
        )
    return out


def get_whole_song_list(
    target_id: str,
    target: Literal["artist", "lyricist", "composer", "arranger"] = "artist",
    mode: int = 4,
    interval: float = 0.1,
) -> list[dict[str, Optional[Any]]]:
    soup = get_target_lyric_soup(
        target_id,
        target,
        mode,
    )
    target_name = soup.select_one("h2.my-2.my-lg-0.mx-2")
    if target_name:
        pat = r".+の歌詞一覧リスト\d+曲"
        m = re.search(pat, target_name.get_text(strip=True))
        if m:
            print(f"{m.group(0)}を取得します")
    ttl_page = parse_total_pages(soup)
    soup_list = [soup]
    for i in range(1, ttl_page):
        soup_list.append(get_target_lyric_soup(target_id, page_no=i))
        time.sleep(interval)
    song_list = []
    for soup in soup_list:
        song_list += get_song_list_from_soup(soup)
    return song_list


def clean_text(text: str) -> str:
    text = text.replace("\n", "<NL>").replace("\u3000", "<NL>")
    res = neologdn.normalize(text)
    res = text.replace("<NL>", " ")
    res = res.lower()
    return res


def get_lyric_and_release(lyrics_url: str, clean: bool = True) -> tuple[Any, Any]:
    response = requests.get(lyrics_url)
    soup = BeautifulSoup(response.text, "html.parser")
    target_div = soup.find("div", {"id": "kashi_area", "itemprop": "text"})
    row_lyric = target_div.get_text(" ").strip() if target_div else ""
    out_lyric = clean_text(row_lyric) if clean else row_lyric

    song_info_part = soup.select_one("p.ms-2.ms-md-3.detail.mb-0")
    song_info = song_info_part.get_text() if song_info_part else ""
    pat = "発売日：(\d{4}/\d{2}/\d{2})"
    m = re.search(pat, song_info)
    release_date = m.group(1) if m else ""
    return out_lyric, release_date


def get_whole_song_lyrics(
    target_id: str,
    target: Literal["artist", "lyricist", "composer", "arranger"] = "artist",
    mode: int = 4,
    sample_n: int | None = None,
    interval: float = 0.1,
) -> list[dict[str, Optional[Any]]]:
    song_list = get_whole_song_list(target_id, target, mode, interval)
    ttl_song_num = len(song_list)
    sample_n = min(sample_n, len(song_list)) if sample_n else len(song_list)
    for i, song in enumerate(song_list[:sample_n]):
        title = song["title"]
        lyrics_url = song["lyrics_url"]
        print(f"全{ttl_song_num}曲中 {i + 1}曲目 取得中 {title:<100}", end="\r")
        lyric, release = get_lyric_and_release(lyrics_url) if lyrics_url else ("", "")
        song["lyric"] = lyric
        song["release"] = release
        time.sleep(interval)
    print(f"{sample_n}曲完了{' ':<100}")
    return song_list


if __name__ == "__main__":
    import pickle
    from pathlib import Path

    # artist_id = "31352"
    # artist_id = "17598"
    artist_id = "39"
    # print(get_whole_song_list(artist_id))

    res = get_whole_song_lyrics(target_id=artist_id)
    path = (
        Path("/Users/yutaro/Documents/python/project/spotify_audio_feature/data")
        / f"{artist_id}.pkl"
    )
    with open(path, mode="wb") as f:
        pickle.dump(res, f)
