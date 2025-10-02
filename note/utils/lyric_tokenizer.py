import re
import unicodedata
from typing import Iterable, Sequence

from sudachipy import dictionary
from sudachipy import tokenizer as sudachi_tokenizer

_TOK = dictionary.Dictionary(dict="full").create()
_SPLIT_MODE = sudachi_tokenizer.Tokenizer.SplitMode.C
# もし環境にSudachiが無い場合は、呼び出し側で注入できるようにする
# base_tokenize(..., tok=_TOK, split_mode=_SPLIT_MODE) で上書き可能にする設計もアリ

# === 設定（最小限＆命名揃え） ===
DEFAULT_KEEP_POS = {"名詞", "形容詞", "動詞", "代名詞", "連体詞"}

# 「前処理で消すノイズ文字」だけ定義（トークン後に弾く対象と混ぜない）
NOISE_CHARS = set("?？「」.-！!(（)）…・")

# かな・記号的だけを弾くためのレンジ判定（過剰フィルタの副作用を減らす）
# _KANA_OR_SYMBOL_RE = re.compile(r"^[\u3040-\u309F\u30A0-\u30FFー・\-!?！？：:、。…]+$")

# スペース分割（全角スペース含む：NFKC後なら半角に正規化）
_SPACE_SPLIT = re.compile(r"\s+")

# NGワード
NG_SURFACE: set = set()


def normalize_baseform(m):
    pos0 = m.part_of_speech()[0]
    # 動詞・形容詞は基本形、それ以外は表層
    return m.dictionary_form() if pos0 in {"動詞", "形容詞"} else m.surface()


def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _clean_text(text: str) -> str:
    # NFKC → 指定ノイズ削除（空白は残す）
    text = _nfkc(text)
    if NOISE_CHARS:
        table = str.maketrans("", "", "".join(NOISE_CHARS))
        text = text.translate(table)
    return text


def _iter_space_chunks(
    text: str,
    max_chars: int = 2000,
    hard_max_chars: int = 4000,
) -> Iterable[str]:
    """
    スペース境界で max_chars を超えないようにチャンク化。
    - 1語が hard_max_chars を超える場合は語内強制分割。
    - バッファ全体が hard_max_chars を超えた場合も保守的に吐き出す（安全弁）。
    """
    if not text:
        return
    parts = _SPACE_SPLIT.split(text.strip())

    buf: list = []
    cur_len = 0
    for p in parts:
        if not p:
            continue
        add_len = (1 if buf else 0) + len(p)
        if cur_len + add_len > max_chars and buf:
            yield " ".join(buf)
            buf = [p]
            cur_len = len(p)
        else:
            buf.append(p)
            cur_len += add_len

        # 語自体が異常に長い場合は語内分割
        while len(buf[-1]) > hard_max_chars:
            long_piece = buf.pop()
            yield long_piece[:hard_max_chars]
            rest = long_piece[hard_max_chars:]
            if rest:
                buf.append(rest)
            cur_len = sum(len(x) for x in buf) + max(0, len(buf) - 1)

        # バッファ全体のフェイルセーフ
        if cur_len > hard_max_chars:
            out = []
            total = 0
            for i, w in enumerate(buf):
                add = len(w) + (1 if i > 0 else 0)
                if total + add > hard_max_chars:
                    break
                out.append(w)
                total += add
            if out:
                yield " ".join(out)
                buf = buf[len(out) :]
                cur_len = sum(len(x) for x in buf) + max(0, len(buf) - 1)

    if buf:
        yield " ".join(buf)


def base_tokenize(
    text: str,
    keep_pos: Sequence[str] | str | bool = True,
    ng_words: Sequence[str]
    | str
    | bool = False,  # デフォは使わない（前処理で消してるため）
    max_chars_per_chunk: int = 2000,
    hard_max_chars: int = 4000,
    tok=None,
    split_mode=None,
):
    """
    長文を安全に分割してから Sudachi に渡す版。
    - 大域デフォルト(tok/_SPLIT_MODE)が無ければ実行時エラーを明示。
    """
    if tok is None:
        tok = _TOK
    if split_mode is None:
        split_mode = _SPLIT_MODE
    if tok is None or split_mode is None:
        raise RuntimeError("Sudachi tokenizer (tok) / split_mode が未初期化です。")

    # keep_pos 正規化
    if isinstance(keep_pos, bool):
        _keep_pos = set(DEFAULT_KEEP_POS) if keep_pos else set()
    elif isinstance(keep_pos, str):
        _keep_pos = {keep_pos}
    else:
        _keep_pos = set(keep_pos)

    # ng_words 正規化
    if isinstance(ng_words, bool):
        _ng_words = set() if not ng_words else set(NG_SURFACE)  # True は使わない前提
    elif isinstance(ng_words, str):
        _ng_words = {ng_words}
    else:
        _ng_words = set(ng_words)

    cleaned = _clean_text(text)
    toks: list[str] = []

    for chunk in _iter_space_chunks(
        cleaned, max_chars=max_chars_per_chunk, hard_max_chars=hard_max_chars
    ):
        if not chunk:
            continue
        # 例外が起きても他チャンクは処理継続
        try:
            for m in tok.tokenize(chunk, split_mode):
                pos0 = m.part_of_speech()[0]
                if _keep_pos and pos0 not in _keep_pos:
                    continue
                surf = normalize_baseform(m)

                # NGワード弾き（使う場合のみ）
                if _ng_words and (not surf or surf in _ng_words):
                    continue

                # # かな・記号的なもののみは弾く（過剰フィルタしない）
                # if surf and _KANA_OR_SYMBOL_RE.fullmatch(surf):
                #     continue

                if surf:
                    toks.append(surf)
        except Exception:
            # ログ仕込みたければここで
            continue

    return toks
